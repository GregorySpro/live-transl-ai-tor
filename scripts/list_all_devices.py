import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()
print(f"Total devices: {pa.get_device_count()}\n")
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    loop = "[LOOPBACK]" if d.get("isLoopbackDevice") else ""
    ins = d["maxInputChannels"]
    outs = d["maxOutputChannels"]
    rate = int(d["defaultSampleRate"])
    name = d["name"]
    print(f"[{i:2d}] in={ins} out={outs} {rate}Hz  {name} {loop}")
pa.terminate()
