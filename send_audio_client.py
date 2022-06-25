from typing import List
from socket import getaddrinfo, socket, AF_INET, AF_INET6, IPPROTO_TCP, SOCK_STREAM, error as socket_error, timeout as socket_timeout
from queue import Queue, Empty
from threading import Thread
from audio_stream_common import DevicePicker, st_init_audio_info, pyaudio, pick_device, load_settings
from array import array
from sys import byteorder


audio = None
sock = None


def read_thread(lst_sentinel):
    q, audio, exception_on_overflow, frames_per_block = lst_sentinel[:4]
    try:
        while lst_sentinel[-1]:
            q.put(audio.read(frames_per_block, exception_on_overflow))
            lst_sentinel[-2] = True
    finally:
        lst_sentinel[-1] = False


def main(argv: List[str]):
    global audio
    global sock
    assert len(argv) in [0, 1]
    if len(argv) == 1:
        assert argv[0] in ["--use-defaults"]
    use_defaults = len(argv) and argv[0] == "--use-defaults"
    print("use_defaults =", use_defaults, "argv =", argv)
    settings = load_settings({
        "connect_host": "",
        "connect_port": "3123",
        "exception_on_overflow": True,
        "frames_per_block": None,
        "max_input_channels": float("inf"),
        "default_input_device_name_contains": ["CABLE Output"],
        "getaddrinfo_af_arg": "AF_ANY",
        "send_volume_percent": 100,
    })
    gai_af_arg = {
        "AF_ANY": 0,
        "AF_INET": AF_INET,
        "AF_INET6": AF_INET6,
    }[settings["getaddrinfo_af_arg"]]
    pa = pyaudio.PyAudio()
    dp = DevicePicker(pa, "input")
    dp.find_new_default_device(
        lambda name_contains, dev: name_contains in dev["name"],
        settings["default_input_device_name_contains"]
    )
    dev_info = dp.pick(not use_defaults)
    print(dev_info)
    host = ""
    if not use_defaults:
        host = input(f"Host [default {settings['connect_host']}]: ")
    if len(host) == 0:
        host = settings["connect_host"]
    port = ""
    if not use_defaults:
        port = input(f"Port [default {settings['connect_port']}]: ")
    if len(port) == 0:
        port = settings["connet_port"]
    send_volume_percent = settings["send_volume_percent"]
    retry = True
    while retry:
        retry = False
        sock = None
        for af, typ, proto, ca, sa in getaddrinfo(host, port, gai_af_arg, SOCK_STREAM, IPPROTO_TCP):
            if af not in [AF_INET, AF_INET6]:
                continue
            sock = socket(af, typ, proto)
            print(f"found configuration for resolved address {repr(sa)}")
            try:
                sock.connect(sa)
                break
            except socket_error:
                sock = None
                print("  FAILED: could not connect")
                continue
        assert sock is not None, "Could not find or connect to any hosts"
        audio = pa.open(
            input=True,
            input_device_index=dev_info["index"],
            rate=int(dev_info["defaultSampleRate"]),
            channels=min(dev_info["maxInputChannels"], settings["max_input_channels"]),
            format=pyaudio.paInt16
        )
        frames_per_block = audio._frames_per_buffer if settings["frames_per_block"] is None else settings["frames_per_block"]
        print(f"using frames_per_block = {frames_per_block}")
        sock.sendall(st_init_audio_info.pack(audio._format, audio._channels - 1, audio._rate - 1, frames_per_block - 1))
        q = Queue()
        lst_sentinel = [q, audio, settings["exception_on_overflow"], frames_per_block, False, True]
        thrd = Thread(target=read_thread, args=(lst_sentinel,))
        thrd.start()
        is_dropping = False
        try:
            while lst_sentinel[-1]:
                try:
                    gotten = q.get(timeout=1)
                except Empty:
                    continue
                if q.qsize() > 10 or is_dropping:
                    is_dropping = q.qsize() > 2
                    print(f"Dropping block, ({q.qsize()} items in the queue is too much)")
                else:
                    if send_volume_percent != 100:
                        arr = array('h', gotten)
                        swap = byteorder == "big"
                        if swap:
                            arr.byteswap()
                        for i in range(len(arr)):
                            arr[i] = min(max(arr[i] * send_volume_percent / 100, -32768), 32767)
                        if swap:
                            arr.byteswap()
                        sock.sendall(memoryview(arr))
                    else:
                        sock.sendall(gotten)
        finally:
            if not lst_sentinel[-1] and not lst_sentinel[-2]:
                settings["frames_per_block"] = frames_per_block + 1
                print("FAILURE: attempting reload with different frames_per_block")
                retry = True
            lst_sentinel[-1] = False
            thrd.join()
            try:
                sock.close()
            except:
                pass
            
    return audio


if __name__ == "__main__":
    import sys
    audio = main(sys.argv[1:])
