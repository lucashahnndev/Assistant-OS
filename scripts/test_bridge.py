import sys
import os
import json
import logging
from typing import Dict, Any

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(os.path.join(project_root, 'src'))

from core.orchestrator import AgentOrchestrator
from core.identity import PrincipalContext
from utils.logging_config import setup_logging

# Setup minimalist logging for the bridge
setup_logging()
logger = logging.getLogger("TestBridge")

# Color codes
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

class TestBridge:
    def __init__(self, session_id="test_user"):
        self.orchestrator = AgentOrchestrator()
        self.session_id = session_id
        self.context = PrincipalContext(
            interface="cli",
            sender_id=session_id,
            session_id=session_id
        )
        # Ensure the test user is approved for access control
        self.orchestrator.access_controller.pre_llm_gate(self.context)
        user = self.orchestrator.access_controller.identity_service.get_user("cli", session_id)
        if user and user.status != "approved":
            user.status = "approved"
            self.orchestrator.access_controller.identity_service.save_user(user)

        # Initialize BrowserDriver with a lightweight kernel stub
        try:
            from drivers.browser_driver import BrowserDriver

            class _KernelStub:
                """Minimal kernel-like object for BrowserDriver."""
                def __init__(self, config_manager, playback_service, sessions):
                    self.config_manager = config_manager
                    self.playback_service = playback_service
                    self.sessions = sessions
                    self.browser_driver = None

            stub = _KernelStub(
                self.orchestrator.config_manager,
                self.orchestrator.playback_service,
                self.orchestrator.sessions,
            )
            self.browser_driver = BrowserDriver(kernel=stub)
            stub.browser_driver = self.browser_driver
            self.browser_driver.start()
            self.orchestrator.set_browser_driver(self.browser_driver)
            print(f"{YELLOW}BrowserDriver initialized (Playwright).{RESET}")
        except Exception as e:
            self.browser_driver = None
            print(f"{RED}BrowserDriver not available: {e}{RESET}")

        print(f"{YELLOW}Atlas Test Bridge Initialized (Session: {session_id}){RESET}")
        print(f"Type {BLUE}/help{RESET} for special commands.")

    def run(self):
        while True:
            try:
                user_input = input(f"\n{GREEN}User > {RESET}").strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        break
                    continue

                self.process_message(user_input)

            except KeyboardInterrupt:
                print("\nExiting Bridge...")
                break
            except Exception as e:
                print(f"{RED}Error in bridge loop: {e}{RESET}")

    def handle_command(self, cmd):
        parts = cmd.split()
        main_cmd = parts[0].lower()

        if main_cmd in ["/exit", "/quit"]:
            return False
        
        elif main_cmd == "/help":
            print(f"""
{BLUE}Available Commands:{RESET}
  /memory      - Show current session memory and history
  /context     - Show the TOON state summary sent to LLM
  /skills      - List available skill actions
  /clear       - Clear session history
  /session <ID>- Switch to a different session ID
  /help        - Show this help message
  /exit        - Exit the bridge
            """)

        elif main_cmd == "/memory":
            session = self.orchestrator.get_session_robust(self.session_id)
            if session:
                print(f"\n{BLUE}--- SESSION MEMORY ({self.session_id}) ---{RESET}")
                for msg in session.history:
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')
                    mtype = msg.get('type', 'message')
                    color = BLUE if role == 'assistant' else GREEN if role == 'user' else YELLOW
                    print(f"{color}[{role.upper()}] ({mtype}): {content}{RESET}")
            else:
                print(f"{RED}No active session found for {self.session_id}{RESET}")

        elif main_cmd == "/context":
            session = self.orchestrator.get_session_robust(self.session_id)
            if session:
                print(f"\n{BLUE}--- TOON STATE SUMMARY ---{RESET}")
                print(json.dumps(session.state_summary, indent=2, ensure_ascii=False))
            else:
                print(f"{RED}No active session found.{RESET}")

        elif main_cmd == "/skills":
            summary = self.orchestrator.skill_registry.get_summary()
            print(f"\n{BLUE}--- AVAILABLE SKILLS ---{RESET}")
            print(summary)

        elif main_cmd == "/clear":
            self.orchestrator.delete_session(self.session_id)
            print(f"{YELLOW}Session {self.session_id} cleared.{RESET}")

        elif main_cmd == "/session":
            if len(parts) > 1:
                self.session_id = parts[1]
                print(f"{YELLOW}Switched to session: {self.session_id}{RESET}")
            else:
                print(f"{RED}Usage: /session <session_id>{RESET}")

        else:
            print(f"{RED}Unknown command: {main_cmd}{RESET}")
        
        return True

    def process_message(self, text):
        print(f"{BLUE}Atlas is thinking...{RESET}", end="\r")
        
        # Simple callback to print progress
        def on_status(session_id, phase, payload=None):
            label = payload.get('label', phase) if isinstance(payload, dict) else phase
            print(f"{YELLOW}[STATUS] {label}{RESET}" + " " * 20)

        def on_reasoning(*args, **kwargs):
            chunk = kwargs.get('chunk') or (args[1] if len(args) > 1 else str(args))
            print(f"{YELLOW}[THOUGHT] {chunk}{RESET}")

        callbacks = {
            'send_status': on_status,
            'send_reasoning_chunk': on_reasoning,
            'send_response': lambda t, **kwargs: print(f"\n{BLUE}Atlas > {RESET}{t}")
        }

        try:
            # We bypass the Kernel and call Orchestrator directly for simpler terminal output
            # Note: Kernel.process_input handles threading/workers, here we use sync for simplicity
            self.orchestrator.process(text, session_id=self.session_id, callbacks=callbacks, context=self.context)
        except Exception as e:
            print(f"\n{RED}Error processing message: {e}{RESET}")

if __name__ == "__main__":
    # Ensure it's run from scripts directory or root
    bridge = TestBridge()
    bridge.run()
