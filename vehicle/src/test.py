import pigpio
import time

pi = pigpio.pi()


pi.set_servo_pulsewidth(20, 500)
time.sleep(3)
for i in range(500, 2600, 50):
    print(i)
    pi.set_servo_pulsewidth(20, i)
    time.sleep(0.25)

