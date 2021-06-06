from struct import Struct
from typing import Callable
import pyaudio
from os.path import dirname, join, abspath
from json import load, dump

settings_filename = join(dirname(abspath(__file__)), "settings.json")


def load_settings(defaults):
    try:
        fl = open(settings_filename, "r")
    except IOError:
        with open(settings_filename, "w") as fl:
            dump(defaults, fl)
        return defaults
    else:
        try:
            data = load(fl)
            fl.seek(0)
            data_copy = load(fl)
        finally:
            fl.close()
    for k in defaults:
        data.setdefault(k, defaults[k])
    if data != data_copy:
        with open(settings_filename, "w") as fl:
            dump(data, fl)
    return data

st_init_audio_info = Struct("<HBHH")

class DevicePicker(object):
    def __init__(self, pa: pyaudio.PyAudio, typ: str):
        assert typ in ["input", "output"]
        self.pa = pa
        self.typ = typ
        self.opposite_typ, self.channels_key = {
            "input": ("output", "maxInputChannels"),
            "output": ("input", "maxOutputChannels")
        }[typ]
        num_devs = pa.get_device_count()
        self.lst_info = [
            pa.get_device_info_by_index(i)
            for i in range(num_devs)
        ]
        self.default_info = (
            pa.get_default_output_device_info()
            if typ == "output" else
            pa.get_default_input_device_info()
        )
    
    def pick(self, ask_user=True):
        fmt_str = f"%0{len(str(len(self.lst_info) - 1))}u: %s"
        for inf in self.lst_info:
            if inf[self.channels_key] > 0:
                print(fmt_str % (inf["index"], inf["name"]))
        if not ask_user:
            print(f"Using device index {self.default_info['index']}")
            return self.default_info
        while True:
            inp = input(f"Enter index [default {self.default_info['index']}]: ")
            if len(inp) == 0:
                return self.default_info
            try:
                val = int(inp)
            except ValueError:
                print("Invalid integer for index")
                continue
            if val < 0:
                print("Must be non-negative integer for index")
                continue
            elif val >= len(self.lst_info):
                print(f"Must not be higher than {len(self.lst_info) - 1} for index")
                continue
            dev_info = self.lst_info[val]
            if dev_info[self.channels_key]:
                return dev_info
            print(f"Device must have {self.typ} channels (you probably picked an {self.opposite_typ} device)")
    
    def find_new_default_device(self, fn_dev_matches, lst_try_fn: list):
        for try_fn_arg in lst_try_fn:
            for dev in self.lst_info:
                if dev[self.channels_key] == 0:
                    continue
                if fn_dev_matches(try_fn_arg, dev):
                    self.default_info = dev
                    break
            else:
                continue
            break

def pick_device(pa: pyaudio.PyAudio, typ: str) -> dict:
    dp = DevicePicker(pa, typ)
    return dp.pick()
