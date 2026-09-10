"""Create deterministic synthetic files; refuses to overwrite existing inputs."""
import argparse
from pathlib import Path
import random


def generate(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    original = bytearray(random.Random(44).randbytes(65536))
    tag = b'\x00ECU:DEMO_ONLY HW:DEMO_HW SW:DEMO_SW CAL:DEMO_CAL\x00'
    original[:len(tag)] = tag
    tuned = original.copy()
    for start, length in [(0x1200, 128), (0x2400, 80), (0x5800, 42)]:
        for i in range(start, start + length):
            tuned[i] ^= 0x11
    stage2 = tuned.copy()
    stage2[0x7000:0x7020] = bytes(v ^ 0x22 for v in original[0x7000:0x7020])
    for name, data in [('original_demo.bin', original), ('tuned_demo.bin', tuned),
                       ('demo_stage2.bin', stage2), ('new_demo.bin', original)]:
        with (folder / name).open('xb') as stream:
            stream.write(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', nargs='?', default='demo_files')
    generate(Path(parser.parse_args().folder))
