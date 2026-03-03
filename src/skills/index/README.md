# Available Skills Index

This is a list of available skill categories. Use `my_skills --detail [name]` for usage instructions.

- **browser_controller**: Controle avançado de interface web (`browser_agent`).
- **web_search_connected**: Busca autônoma e conectada na web (`search_web_connected`).
- **system_control**: Monitor system status (`hw_info`, `os_info`).
- **process_control**: Manage processes (`process_list`, `process_find`, `process_kill`).
- **power_control**: Manage power (`reboot`, `shutdown`).
- **inventory_control**: List apps/packages (`list_installed_apps`, `list_installed_packages`).
- **service_control**: systemd operations (`service_status`, `service_restart`).
- **network_control**: Networking (`net_status`, `ping`).
- **fs_control**: File operations (`fs_list`, `fs_read`).
- **terminal_control**: Shell access (`execute_command`).
- **system_apps**: App management (`open_program`, `close_program`).
- **web_search**: Search (`search_web`, `search_in_maps`).
- **memory_management**: Memory (`store_memory`, `recall_memory`).
- **data_analysis**: Análise de dados tabulares/séries e geração de tabela para cards de gráfico (`data.analysis.summarize`).
- **system_logs**: Internal logs (`system_logs`).
- **play_music**: Media control (`play_music`, `stop_music`).

---
### 🧠 Agente: Protocolo de Raciocínio
Você opera em um loop **THOUGHT -> ACTION -> OBSERVATION -> REFLECTION**.
Sempre que uma ação for executada, utilize o passo de **THOUGHT** seguinte para refletir sobre o resultado e ajustar seu plano (`plan`) conforme necessário.
Se uma ferramenta falhar, use o raciocínio para diagnosticar o erro em vez de repetir a mesma ação.
