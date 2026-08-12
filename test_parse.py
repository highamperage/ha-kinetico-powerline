import sys
import os
sys.path.insert(0, os.path.abspath('custom_components/kinetico_powerline'))
from protocol import parse_dashboard_packets

v_packet = bytearray([0x76, 0x76, 0x00, 0x00, 0x00, 0x08, 0x00, 0x17] + [0]*11 + [0x42])
u_packet = bytearray([0x75, 0x75, 0x01, 0x00, 0x00, 50, 0x00, 0x00] + [0]*11 + [0x3A])
res = parse_dashboard_packets([v_packet, u_packet], 410)

print('Total grains:', res.total_capacity_grains)
print('Gallons:', res.capacity_remaining_gallons)
