// Minimal levelled logging over the USB serial console.
//
// The Raspberry Pi build used bare `print()` calls prefixed with the module
// name; this keeps the same shape but honours `config.log_level` so a noisy
// service can be silenced without editing it.
#pragma once

#include <Arduino.h>

enum class LogLevel { Debug = 0, Info = 1, Warn = 2, Error = 3 };

namespace logs {

// Applies `config.log_level` ("DEBUG" | "INFO" | "WARN" | "ERROR").
void init();
void setLevel(LogLevel level);
LogLevel level();

void log(LogLevel level, const char* tag, const char* fmt, ...);

}  // namespace logs

#define LOG_DEBUG(tag, ...) logs::log(LogLevel::Debug, tag, __VA_ARGS__)
#define LOG_INFO(tag, ...) logs::log(LogLevel::Info, tag, __VA_ARGS__)
#define LOG_WARN(tag, ...) logs::log(LogLevel::Warn, tag, __VA_ARGS__)
#define LOG_ERROR(tag, ...) logs::log(LogLevel::Error, tag, __VA_ARGS__)
