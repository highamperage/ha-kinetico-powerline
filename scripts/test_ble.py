import asyncio
from bleak import BleakScanner, BleakClient
import importlib.util
import sys
import os

# Load protocol.py directly
spec = importlib.util.spec_from_file_location("protocol", os.path.abspath("custom_components/kinetico_powerline/protocol.py"))
protocol = importlib.util.module_from_spec(spec)
sys.modules["protocol"] = protocol
spec.loader.exec_module(protocol)

async def scan_and_connect():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover(timeout=5.0)
    target = None
    for d in devices:
        if d.name and d.name.startswith(protocol.DEVICE_NAME_PREFIXES):
            print(f"Found Kinetico Device: {d.name} [{d.address}]")
            target = d
            break
            
    if not target:
        print("No device found.")
        return

    print(f"Connecting to {target.address}...")
    
    collected_responses = []
    response_event = asyncio.Event()

    def notification_handler(sender, data):
        print(f"Notification from {sender}: {data.hex()} (len={len(data)})")
        collected_responses.append(bytes(data))
        response_event.set()

    async with BleakClient(target.address) as client:
        print("Connected!")
        
        uart = None
        for svc in protocol.UART_SERVICES:
            if client.services.get_service(svc["service"]):
                uart = svc
                break
                
        if not uart:
            print("UART service not found.")
            return
            
        print("Starting notifications...")
        await client.start_notify(uart["rx_char"], notification_handler)
        await asyncio.sleep(0.5)

        print("Sending Handshake...")
        collected_responses.clear()
        response_event.clear()
        await client.write_gatt_char(uart["tx_char"], protocol.cmd_handshake(), response=False)
        await asyncio.sleep(1.0)
        
        if not collected_responses:
            print("No handshake response")
            return
            
        hs_data = collected_responses[-1]
        hs = protocol.parse_handshake(hs_data, len(hs_data))
        print(f"Handshake: fw={hs.firmware_string}, auth={hs.auth_status}, type={hs.device_type.friendly_name()}")
        
        if hs.firmware_version >= 420 and hs.auth_status == protocol.AuthStatus.NOT_AUTHENTICATED:
            print("Authenticating...")
            collected_responses.clear()
            response_event.clear()
            if hs.pin_required:
                cmd = protocol.cmd_auth(counter=hs.connection_counter, pin=1234, fw_420_plus=True)
            else:
                cmd = protocol.cmd_auth_pa(counter=hs.connection_counter, pin=1234)
            await client.write_gatt_char(uart["tx_char"], cmd, response=False)
            await asyncio.sleep(1.0)
            
        print("Sending Dashboard Request...")
        collected_responses.clear()
        response_event.clear()
        
        await client.write_gatt_char(uart["tx_char"], protocol.cmd_advanced_settings(), response=False)
        await asyncio.sleep(1.0)
        
        await client.write_gatt_char(uart["tx_char"], protocol.cmd_dashboard(), response=False)
        await asyncio.sleep(2.0)
        
        print(f"Received {len(collected_responses)} dashboard packets.")
        dashboard = protocol.parse_dashboard_packets(
            collected_responses, 
            hs.firmware_version, 
            hs.device_type
        )
        
        if dashboard:
            print(f"Hardness: {dashboard.hardness_gpg} GPG")
            print(f"Capacity Remaining %: {dashboard.capacity_remaining_percent}%")
            print(f"Capacity Remaining Gal: {dashboard.capacity_remaining_gallons} Gal")
            print(f"Total Capacity Grains: {dashboard.total_capacity_grains}")
            print(f"Config Hardness: {dashboard.config_hardness_gpg} GPG")
            print(f"Salt Sensor: {dashboard.salt_sensor}%")
            print(f"Days Since Regen: {dashboard.days_since_regen}")
            print(f"Days Until Regen: {dashboard.days_until_regen}")
        else:
            print("Failed to parse dashboard data.")

if __name__ == "__main__":
    asyncio.run(scan_and_connect())
