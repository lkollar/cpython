import time
import os


def foo(x):
    bar(x)


def bar(x):
    if x % 2 == 0:
        baz(x)
    else:
        baz2(x)


def baz(x):
    time.sleep(0.001)
    print(f"baz() {x}")


def baz2(x):
    time.sleep(0.001)
    print(f"baz2() {x}")


def do_things():
    for i in range(100000):
        if i % 2 == 0:
            foo(i)
        else:
            baz2(i)


input(f"PID: {os.getpid()} Press Enter to start profiling...")
do_things()
