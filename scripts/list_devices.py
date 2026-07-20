import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()

print("=== Tous les devices audio ===")
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    is_loop = d.get("isLoopbackDevice", False)
    tag = " [LOOPBACK]" if is_loop else ""
    if d.get("maxInputChannels", 0) > 0 or is_loop:
        name = d["name"][:60]
        ins = d["maxInputChannels"]
        outs = d["maxOutputChannels"]
        print(f"  [{i}] {name}  in={ins} out={outs}{tag}")

print()
print("=== WASAPI default output ===")
try:
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    out_idx = wasapi["defaultOutputDevice"]
    dev = pa.get_device_info_by_index(out_idx)
    print(f"  index: {out_idx}")
    print(f"  name: {dev['name']}")
    print(f"  rate: {dev['defaultSampleRate']}")
except Exception as e:
    print(f"  erreur: {e}")

pa.terminate()
