import os
import urllib.request
import json

APP_ID    = os.environ['DISCORD_APPLICATION_ID']
BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']

commands = [
    {
        'name': 'status',
        'description': 'Get shipment status',
        'options': [{'name': 'shipment_id', 'description': 'Shipment ID (e.g. SHIP-001)', 'type': 3, 'required': True}],
    },
    {'name': 'alerts', 'description': 'List active alerts'},
    {
        'name': 'resolve',
        'description': 'Resolve an alert',
        'options': [{'name': 'alert_id', 'description': 'Alert ID', 'type': 3, 'required': True}],
    },
    {
        'name': 'lock',
        'description': 'Lock a shipment',
        'options': [{'name': 'shipment_id', 'description': 'Shipment ID', 'type': 3, 'required': True}],
    },
    {
        'name': 'unlock',
        'description': 'Unlock a shipment',
        'options': [{'name': 'shipment_id', 'description': 'Shipment ID', 'type': 3, 'required': True}],
    },
]

url = f'https://discord.com/api/v10/applications/{APP_ID}/commands'
req = urllib.request.Request(
    url,
    data=json.dumps(commands).encode(),
    headers={'Authorization': f'Bot {BOT_TOKEN}', 'Content-Type': 'application/json'},
    method='PUT',
)
resp = urllib.request.urlopen(req)
print('Registered:', json.loads(resp.read()))
