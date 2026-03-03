#!/usr/bin/env python3
import sys
import os
import json
import logging
import argparse
import asyncio
import time
from typing import Dict, Any, List

# Add src to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(project_root, 'src'))

from core.identity import PrincipalContext
from utils.logging_config import setup_logging
from utils.privileged_setup import setup_privileged_access, check_privileged_access
import main as init_main

# Color codes
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"

class AgentCLI:
    def __init__(self, args):
        self.args = args
        self.session_id = args.session or "cli_user"
        
        # Suppress noisy logs unless requested
        log_level = logging.DEBUG if args.verbose > 1 else logging.INFO
        if args.quiet:
            log_level = logging.ERROR
            
        setup_logging()
        # Fine-tune specific loggers to avoid clutter in clean mode
        if not args.verbose:
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("openai").setLevel(logging.WARNING)
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("Kernel").setLevel(logging.WARNING)
            logging.getLogger("AgentOrchestrator").setLevel(logging.WARNING)

            logging.getLogger("AgentOrchestrator").setLevel(logging.WARNING)

        # Use a separate PID file for CLI tools to prevent conflict with background Server/Telegram
        init_main.PID_FILE = f"agent_cli_{os.getpid()}.pid"
        self.kernel = init_main.Kernel()
        self.orchestrator = self.kernel.orchestrator
        
        self.context = PrincipalContext(
            interface="cli",
            sender_id=self.session_id,
            session_id=self.session_id
        )
        
        # Pre-approve CLI interface via AccessController
        self.orchestrator.access_controller.identity_service.policy["interfaces"]["cli"] = {
            "dm_mode": "anyone",
            "group_mode": "anyone",
            "allow_anyone_in_chats": [],
            "rate_limit_enabled": False,
            "max_msgs_per_min": 1000
        }
        
        # Ensure the user is registered in the IdentityService
        self.orchestrator.access_controller.pre_llm_gate(self.context)


    def run(self):
        if self.args.command:
            self.process_message(self.args.command)
        else:
            self.interactive_loop()

    def interactive_loop(self):
        print(f"{BLUE}Agent CLI Shell (Session: {self.session_id}){RESET}")
        print(f"Type {DIM}/help{RESET} for commands or {DIM}/exit{RESET} to quit.")
        
        while True:
            try:
                prompt = f"\n{GREEN}agent > {RESET}"
                user_input = input(prompt).strip()
                
                if not user_input:
                    continue
                if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
                    break
                if user_input.startswith("/"):
                    self.handle_meta_command(user_input)
                    continue
                
                self.process_message(user_input)
                
            except KeyboardInterrupt:
                print("\nInterrupted. Use /exit to quit.")
            except EOFError:
                break
            except Exception as e:
                print(f"{RED}Error: {e}{RESET}")

    def handle_meta_command(self, cmd):
        parts = cmd.split()
        main_cmd = parts[0].lower()
        
        if main_cmd == "/help":
            print(f"""
{BLUE}Internal Commands:{RESET}
  /memory   - Show session history
  /clear    - Clear current session
  /skills   - List available tools
  /exit     - Exit CLI
            """)
        elif main_cmd == "/memory":
            session = self.orchestrator.get_session_robust(self.session_id)
            for m in session.history:
                print(f"{DIM}[{m['role'].upper()}]:{RESET} {m['content']}")
        elif main_cmd == "/skills":
            print(self.orchestrator.skill_registry.get_summary())
        elif main_cmd == "/clear":
            self.orchestrator.delete_session(self.session_id)
            print(f"{YELLOW}Session cleared.{RESET}")
        else:
            print(f"{RED}Unknown command: {main_cmd}{RESET}")

    def process_message(self, text):
        if self.args.verbose:
            print(f"{DIM}Thinking...{RESET}", end="\r")
            
        def on_status(phase, payload=None):
            if self.args.verbose:
                label = payload.get('label', phase) if isinstance(payload, dict) else phase
                print(f"{YELLOW}[STATUS] {label}{RESET}" + " " * 10)

        def on_reasoning(chunk):
            if self.args.verbose:
                print(f"{BLUE}[REASON] {chunk}{RESET}")

        def on_response(text, **kwargs):
            # Print newline if we were printing status/reasoning
            if self.args.verbose: print() 
            print(f"{text}")

        callbacks = {
            'send_status': on_status,
            'send_reasoning_chunk': on_reasoning,
            'send_response': on_response
        }

        try:
            if self.kernel.browser_driver:
                self.kernel.browser_driver.start()
            self.orchestrator.process(text, session_id=self.session_id, callbacks=callbacks, context=self.context)
        except Exception as e:
            print(f"{RED}Agent Error: {e}{RESET}")
        finally:
            if self.kernel.browser_driver:
                self.kernel.browser_driver.stop()

def main():
    parser = argparse.ArgumentParser(description="Assistant-OS CLI")
    parser.add_argument("mode", nargs="?", default="chat", choices=["chat", "doctor"], help="Run mode: chat (default) or doctor")
    parser.add_argument("-c", "--command", help="Execute a single command and exit")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Show reasoning steps (-vv for more logs)")
    parser.add_argument("-s", "--session", help="Specify a session ID")
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--setup-privileged", action="store_true", help="(doctor mode) Configure sudoers for safe approved sudo commands")
    parser.add_argument("--check-privileged", action="store_true", help="(doctor mode) Check whether privileged sudo setup is active")
    parser.add_argument("--user", help="(doctor mode) Target system user for sudoers rule")
    parser.add_argument("--dry-run", action="store_true", help="(doctor mode) Print generated sudoers content without installing")
    
    args = parser.parse_args()
    if args.setup_privileged:
        args.mode = "doctor"
    if args.check_privileged:
        args.mode = "doctor"

    if args.mode == "doctor":
        if args.check_privileged:
            result = check_privileged_access(user=args.user)
            color = GREEN if result.ok else YELLOW
            print(f"{color}{result.message}{RESET}")
            details = result.details or {}
            if details:
                try:
                    print(json.dumps(details, indent=2, ensure_ascii=False))
                except Exception:
                    print(str(details))
            raise SystemExit(0 if result.ok else 1)

        if not args.setup_privileged:
            print("Doctor mode usage:")
            print("  agent.py doctor --check-privileged [--user <linux_user>]")
            print("  agent.py doctor --setup-privileged [--user <linux_user>] [--dry-run]")
            raise SystemExit(0)

        result = setup_privileged_access(user=args.user, dry_run=args.dry_run)
        if result.ok:
            print(f"{GREEN}{result.message}{RESET}")
            detected = result.details.get("detected_commands", [])
            if detected:
                print(f"Detected commands: {', '.join(detected)}")
            if args.dry_run:
                content = result.details.get("content", "")
                if content:
                    print("\nGenerated sudoers file:\n")
                    print(content)
            raise SystemExit(0)

        print(f"{RED}{result.message}{RESET}")
        details = result.details or {}
        if details:
            try:
                print(json.dumps(details, indent=2, ensure_ascii=False))
            except Exception:
                print(str(details))
        raise SystemExit(1)
    
    cli = AgentCLI(args)
    cli.run()

if __name__ == "__main__":
    main()
