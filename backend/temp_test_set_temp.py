import sys
sys.path.insert(0, r'C:\Daten\LinuxCNC_UI\backend')
from hardware import connection
print('temps before ->', getattr(connection.get_machine_stat(), 'temperatures', None))
connection.execute_sync_cmd('set_temperature', 0, 'extruder', 60)
print('temps after ->', getattr(connection.get_machine_stat(), 'temperatures', None))
