from socket import getaddrinfo, socket, AF_INET, AF_INET6, IPPROTO_TCP, SOCK_STREAM, error as socket_error, timeout as socket_timeout
from queue import Queue
from threading import Thread
from audio_stream_common import st_init_audio_info, pyaudio, pick_device, load_settings


audio = None
sock = None


def read_thread(lst_sentinel):
    q, audio, exception_on_overflow, frames_per_block = lst_sentinel[:4]
    try:
        while lst_sentinel[-1]:
            q.put(audio.read(frames_per_block, exception_on_overflow))
    finally:
        lst_sentinel[-1] = False


def main():
    global audio
    global sock
    settings = load_settings({
        "host": "",
        "port": "3123",
        "exception_on_overflow": True,
        "frames_per_block": None,
        "max_input_channels": float("inf")
    })
    pa = pyaudio.PyAudio()
    dev_info = pick_device(pa, "input")
    print(dev_info)
    audio = pa.open(
        input=True,
        input_device_index=dev_info["index"],
        rate=int(dev_info["defaultSampleRate"]),
        channels=min(dev_info["maxInputChannels"], settings["max_input_channels"]),
        format=pyaudio.paInt16
    )
    host = input(f"Host [default {settings['host']}]: ")
    if len(host) == 0:
        host = settings["host"]
    port = input(f"Port [default {settings['port']}]: ")
    if len(port) == 0:
        port = settings["port"]
    sock = None
    for af, typ, proto, ca, sa in getaddrinfo(host, port, 0, SOCK_STREAM, IPPROTO_TCP):
        if af not in [AF_INET, AF_INET6]:
            continue
        sock = socket(af, typ, proto)
        print(f"found configuration for resolved address {repr(sa)}")
        try:
            sock.connect(sa)
        except socket_error:
            sock = None
            print("  FAILED: could not connect")
            continue
    assert sock is not None, "Could not find or connect to any hosts"
    frames_per_block = audio._frames_per_buffer if settings["frames_per_block"] is None else settings["frames_per_block"]
    sock.sendall(st_init_audio_info.pack(audio._format, audio._channels - 1, audio._rate - 1, frames_per_block - 1))
    q = Queue()
    lst_sentinel = [q, audio, settings["exception_on_overflow"], frames_per_block, True]
    thrd = Thread(target=read_thread, args=(lst_sentinel,))
    thrd.start()
    try:
        while lst_sentinel[-1]:
            gotten = q.get()
            if q.qsize() > 10:
                print(f"Dropping ({q.qsize()} items in the queue is too much")
            else:
                sock.sendall(gotten)
    finally:
        lst_sentinel[-1] = False
        thrd.join()
        try:
            sock.close()
        except:
            pass
    return audio


if __name__ == "__main__":
    audio = main()
