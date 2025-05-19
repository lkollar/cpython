import time
import os

PIPE_PATH = "/tmp/remote_profiler.pipe"


def send_pid_to_pipe(pid):
    if os.path.exists(PIPE_PATH):
        os.unlink(PIPE_PATH)

    os.mkfifo(PIPE_PATH)

    with open(PIPE_PATH, "w") as pipe:
        pipe.write(f"{pid}\n")
        pipe.flush()
        print(
            f"PID {pid} written to {PIPE_PATH}. Waiting for the pipe to be read..."
        )

        while os.path.exists(PIPE_PATH) and os.stat(PIPE_PATH).st_size > 0:
            time.sleep(0.1)


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


try:
    send_pid_to_pipe(os.getpid())
    do_things()
finally:
    if os.path.exists(PIPE_PATH):
        os.remove(PIPE_PATH)
