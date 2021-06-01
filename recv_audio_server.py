from socket import getaddrinfo, socket, AF_INET, AF_INET6, IPPROTO_TCP, SOCK_STREAM, error as socket_error, timeout as socket_timeout
from queue import Queue
from threading import Thread
from audio_stream_common import st_init_audio_info, pyaudio, pick_device, load_settings
from select import select
from time import time
from traceback import format_exc


READABLE = 1
WRITEABLE = 2
EXCEPTABLE = 4


class App(object):
    def __init__(self):
        self.listen_socks = set()
        self.clients = {}
        self.audio_threads = {}
        self.cleanup_handlers = {}
        self.pa = pyaudio.PyAudio()
        self.odev_idx = None
        self.max_out_channels = None
        self.settings = {}

    def init(self):
        self.settings = load_settings({
            "host": "",
            "port": "3123"
        })
        dev_info = pick_device(self.pa, "output")
        self.odev_idx = dev_info["index"]
        self.max_out_channels = dev_info["maxOutputChannels"]

    def sound_thread(self, thread_info):
        audio = thread_info[0]
        q = thread_info[1]
        suggested_timeout = thread_info[2]
        while thread_info[-3]:
            try:
                audio.write(q.get(timeout=suggested_timeout))
            except:
                pass

    def run_network(self):
        clients = self.clients
        host = self.settings["host"]
        port = self.settings["port"]
        for af, typ, proto, ca, sa in getaddrinfo(host, port, 0, SOCK_STREAM, IPPROTO_TCP):
            if af not in [AF_INET, AF_INET6]:
                continue
            sock = socket(af, typ, proto)
            try:
                sock.bind(sa)
            except socket_error:
                continue
            try:
                sock.listen(1)
            except socket_error:
                sock.close()
            else:
                self.listen_socks.add(sock)
        for sock in self.listen_socks:
            f = self.listen_generator(sock)
            clients[sock] = [f, next(f)]

        while len(clients):
            rlist = []
            wlist = []
            xlist = []
            for sock in clients:
                f, requested_status = clients[sock]
                if requested_status & READABLE:
                    rlist.append(sock)
                if requested_status & WRITEABLE:
                    wlist.append(sock)
                if requested_status & EXCEPTABLE:
                    xlist.append(sock)
            try:
                rlist, wlist, xlist = select(rlist, wlist, xlist, 5.0)
            except socket_timeout:
                continue
            except:
                break
            dct_tmp = {}
            for sock in rlist:
                dct_tmp[sock] = dct_tmp.get(sock, 0) | READABLE
            for sock in wlist:
                dct_tmp[sock] = dct_tmp.get(sock, 0) | WRITEABLE
            for sock in xlist:
                dct_tmp[sock] = dct_tmp.get(sock, 0) | EXCEPTABLE
            for sock, status in dct_tmp.items():
                lst = clients[sock]
                try:
                    lst[1] = lst[0].send(status)
                except:
                    cleanup = self.cleanup_handlers.get(sock, None)
                    if cleanup is not None:
                        self.cleanup_handlers[sock]()
                        del self.cleanup_handlers[sock]
                    if sock in self.listen_socks:
                        self.listen_socks.remove(sock)
                        print(f"[{repr(sock.getsockname())}] ERROR: listening socket thread threw exception, terminating\n{format_exc().rstrip()}")
                    else:
                        print(f"[{repr(sock.getpeername())}] ERROR: connection socket thread threw exception, terminating\n{format_exc().rstrip()}")
                    if sock in self.audio_threads:
                        del self.audio_threads[sock]
                    del clients[sock]
                    try:
                        sock.close()
                    except socket_error:
                        pass
        for sock in list(clients):
            cleanup = self.cleanup_handlers.get(sock, None)
            if cleanup is not None:
                self.cleanup_handlers[sock]()
                del self.cleanup_handlers[sock]
            if sock in self.listen_socks:
                self.listen_socks.remove(sock)
                print(f"[{repr(sock.getsockname())}] terminating listening socket thread")
            else:
                print(f"[{repr(sock.getpeername())}] terminating connection socket thread threw exception")
            if sock in self.audio_threads:
                del self.audio_threads[sock]
            del clients[sock]
            try:
                sock.close()
            except socket_error:
                pass

    def listen_generator(self, sock):
        print(f"[{repr(sock.getsockname())}] listening")
        status = yield READABLE
        while True:
            conn, addr = sock.accept()
            f = self.client_generator(conn)
            print(f"[{repr(addr)}] accepted connection")
            self.clients[conn] = [f, next(f)]
            status = yield READABLE

    def client_generator(self, sock):
        status = yield READABLE
        max_out_channels = self.max_out_channels
        buf = bytearray(st_init_audio_info.size)
        mv = memoryview(buf)
        bytes_read = sock.recv_into(mv, len(mv))
        while len(mv) - bytes_read > 0:
            assert bytes_read
            mv = mv[bytes_read:]
            status = yield READABLE
            bytes_read = sock.recv_into(mv, len(mv))
        fmt, nchannels_m1, sample_rate_m1, num_samples_per_block_m1 = st_init_audio_info.unpack(buf)
        nchannels = nchannels_m1 + 1
        num_samples_per_block = num_samples_per_block_m1 + 1
        sample_rate = sample_rate_m1 + 1
        sample_size = pyaudio.get_sample_size(fmt)
        size = num_samples_per_block * sample_size * nchannels
        chop_channels = nchannels > max_out_channels
        if chop_channels:
            print(f"[{repr(sock.getpeername())}] WARN: chopping {nchannels} channles down to {max_out_channels}")
        audio = self.pa.open(
            output_device_index=self.odev_idx,
            output=True,
            format=fmt,
            rate=sample_rate,
            channels=min(nchannels, max_out_channels)
        )
        q = Queue()
        thread_info = [audio, q, num_samples_per_block / sample_rate + 0.1, True, sock, None]
        thrd = Thread(target=App.sound_thread, args=(self, thread_info))
        thread_info[-1] = thrd
        self.audio_threads[sock] = thread_info
        buf = bytearray(size)
        def cleanup():
            thread_info[-3] = False
            thrd.join()
            audio.close()
        print(f"[{repr(sock.getpeername())}] connected and audio stream initialized")
        if chop_channels:
            buf1 = bytearray(len(buf) * max_out_channels // nchannels)
        else:
            buf1 = buf
        dropped_msg_count = 0
        last_msg_ts = 0
        self.cleanup_handlers[sock] = cleanup
        thrd.start()
        while True:
            status = yield READABLE
            mv = memoryview(buf)
            assert bytes_read
            bytes_read = sock.recv_into(mv, len(mv))
            while len(mv) - bytes_read > 0:
                assert bytes_read
                mv = mv[bytes_read:]
                status = yield READABLE
                bytes_read = sock.recv_into(mv, len(mv))
            now = time()
            if q.qsize() < 10:
                if chop_channels:
                    mv = memoryview(buf)
                    mv1 = memoryview(buf1)
                    for i in range(num_samples_per_block):
                        base = sample_size * nchannels * i
                        base1 = sample_size * self.max_out_channels * i
                        for j in range(0, max_out_channels * sample_size, sample_size):
                            mv1[base1 + j: base1 + j + sample_size] = mv[base + j: base + j + sample_size]
                q.put(bytes(buf1))
            else:
                if now - last_msg_ts < 5.0:
                    dropped_msg_count += 1
                    pass
                else:
                    if dropped_msg_count:
                        print(f"[{repr(sock.getpeername())}] Dropping sample block since queue appears overloaded <<<{dropped_msg_count + 1} times>>>")
                        dropped_msg_count = 0
                    else:
                        print(f"[{repr(sock.getpeername())}] Dropping sample block since queue appears overloaded")
                    last_msg_ts = now
            if now - last_msg_ts >= 5.0 and dropped_msg_count:
                print(f"[{repr(sock.getpeername())}] Dropping sample block since queue appears overloaded <<<{dropped_msg_count + 1} times>>>")
                dropped_msg_count = 0


if __name__ == "__main__":
    app = App()
    app.init()
    app.run_network()
