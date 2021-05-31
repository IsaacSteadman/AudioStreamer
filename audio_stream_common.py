from struct import Struct
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

def pick_device(pa: pyaudio.PyAudio, typ: str) -> dict:
    assert typ in ["input", "output"]
    opposite_typ, channels_key = {
        "input": ("output", "maxInputChannels"),
        "output": ("input", "maxOutputChannels")
    }[typ]
    num_devs = pa.get_device_count()
    lst_info = [
        pa.get_device_info_by_index(i)
        for i in range(num_devs)
    ]
    fmt_str = f"%0{len(str(num_devs - 1))}u: %s"
    for inf in lst_info:
        if inf[channels_key] > 0:
            print(fmt_str % (inf["index"], inf["name"]))
    default_info = (
        pa.get_default_output_device_info()
        if typ == "output" else
        pa.get_default_input_device_info()
    )
    while True:
        inp = input(f"Enter index [default {default_info['index']}]: ")
        if len(inp) == 0:
            return default_info
        try:
            val = int(inp)
        except ValueError:
            print("Invalid integer for index")
            continue
        if val < 0:
            print("Must be non-negative integer for index")
            continue
        elif val >= num_devs:
            print(f"Must not be higher than {num_devs - 1} for index")
            continue
        dev_info = lst_info[val]
        if dev_info[channels_key]:
            return dev_info
        print(f"Device must have {type} channels (you probably picked an {opposite_typ} device)")
