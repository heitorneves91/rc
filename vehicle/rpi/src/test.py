import pigpio
import time

pi = pigpio.pi()


def throttle(x: int):
    print(f'throttle {x}')
    pi.set_servo_pulsewidth(19, 1000 + (x%500))

def turn(x: int):
    assert x in range(1250, 1750 + 1)
    print(f'turn {x}')
    pi.set_servo_pulsewidth(19, x)


turn(1250)
time.sleep(2.0)

i = 1250
while i < 1751:
    print(i)
    turn(i)
    time.sleep(0.04)
    i += 1

