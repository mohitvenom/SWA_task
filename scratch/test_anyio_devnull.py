import anyio
import subprocess

async def main():
    try:
        p = await anyio.open_process(["python", "-c", "input('Enter: ')"], stdin=subprocess.DEVNULL)
        await p.wait()
        print("Exit code:", p.returncode)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    anyio.run(main)
