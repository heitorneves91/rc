#include "logs.h"

#include <stdarg.h>

#include "configuration.h"

namespace {

LogLevel current_level = LogLevel::Info;

const char* levelName(LogLevel level) {
    switch (level) {
        case LogLevel::Debug: return "DEBUG";
        case LogLevel::Info: return "INFO";
        case LogLevel::Warn: return "WARN";
        case LogLevel::Error: return "ERROR";
    }
    return "?";
}

}  // namespace

namespace logs {

void init() {
    String want = config.log_level;
    want.toUpperCase();
    if (want == "DEBUG") {
        current_level = LogLevel::Debug;
    } else if (want == "WARN") {
        current_level = LogLevel::Warn;
    } else if (want == "ERROR") {
        current_level = LogLevel::Error;
    } else {
        current_level = LogLevel::Info;
    }
}

void setLevel(LogLevel level) { current_level = level; }

LogLevel level() { return current_level; }

void log(LogLevel level, const char* tag, const char* fmt, ...) {
    if (static_cast<int>(level) < static_cast<int>(current_level)) {
        return;
    }

    char buf[192];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    Serial.printf("[%8lu] %-5s %s: %s\n", static_cast<unsigned long>(millis()),
                  levelName(level), tag, buf);
}

}  // namespace logs
