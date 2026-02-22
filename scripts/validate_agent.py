import sys
import os
import asyncio
from typing import List, Dict

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(os.path.join(project_root, 'src'))

from core.orchestrator import AgentOrchestrator
from core.identity import PrincipalContext

class AgentValidator:
    def __init__(self, session_id="val_session"):
        self.orchestrator = AgentOrchestrator()
        self.session_id = session_id
        self.context = PrincipalContext(
            interface="cli",
            sender_id="sys_admin",
            session_id=session_id
        )
        self.results = []

    async def run_test(self, name: str, prompt: str, expectation: str):
        print(f"\n[TEST: {name}]")
        print(f"Prompt: {prompt}")
        
        # Simple logging of responses
        responses = []
        def on_response(text, **kwargs):
            responses.append(text)
            print(f"Response: {text}")

        callbacks = {
            'send_response': on_response,
            'send_status': lambda p, payload=None: None,
            'send_reasoning_chunk': lambda c: None
        }

        try:
            # Run in orchestrator
            # Note: process is sync but might take time. We wrap it for future async bridge if needed.
            self.orchestrator.process(prompt, session_id=self.session_id, callbacks=callbacks, context=self.context)
            
            # Simple check if any response contained something relevant
            passed = any(expectation.lower() in r.lower() for r in responses)
            self.results.append({"name": name, "passed": passed})
            print(f"Outcome: {'✅ PASS' if passed else '❌ FAIL'}")
        except Exception as e:
            print(f"Error: {e}")
            self.results.append({"name": name, "passed": False, "error": str(e)})

    async def run_suite(self):
        print("Starting Validation Suite...")
        
        # 0. Bootstrap (Register User)
        await self.run_test("Bootstrap", "Olá", "olá")
        
        # 1. Skill Test: System Info
        await self.run_test("Skill: System Info", "Qual o seu status e informações do sistema?", "cpu")
        
        # 2. Skill Test: Weather (Might fail if no provider, but we test dispatch)
        await self.run_test("Skill: Weather", "Como está o tempo em São Paulo?", "graus")

        # 3. Memory Test: Turn 1
        await self.run_test("Memory: Turn 1", "Meu nome é Lucas e eu gosto de café forte.", "lucas")
        
        # 4. Memory Test: Turn 2 (Persistence)
        await self.run_test("Memory: Turn 2", "Qual o meu nome e o que eu gosto de beber?", "café")

        # 5. Coherence/TOON Test
        await self.run_test("Coherence: Plan", "Crie um arquivo chamado test.txt no workspace com o texto 'Hello Atlas'.", "test.txt")

        print("\n--- FINAL REPORT ---")
        passed_count = sum(1 for r in self.results if r['passed'])
        print(f"Total: {len(self.results)} | Passed: {passed_count} | Failed: {len(self.results) - passed_count}")

if __name__ == "__main__":
    validator = AgentValidator()
    asyncio.run(validator.run_suite())
