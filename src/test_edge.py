import asyncio
import sys
import edge_tts

async def main():
    try:
        c = edge_tts.Communicate('teste', 'pt-BR-FabioNeural')
        await c.save('test.mp3')
        print("SUCCESS")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == '__main__':
    asyncio.run(main())
