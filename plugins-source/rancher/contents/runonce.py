# common code
from _nodes_shared import *

# todo: timeout waiting for service start?
# todo: raise exception if no data is recieved at all?

# check if is start-once service
is_start_once = (os.environ.get('RD_NODE_START_ONCE', 'false').lower() == 'true')
if not is_start_once:
    raise Exception("Can't run, isn't start-once service!")

# setup websocket for reading log output
api_data_logs = {
    "follow": True,
    "lines": 1
}
api_url_logs = "{}/containers/{}?action=logs".format(api_base_url, node_id)
api_res_logs = requests.post(api_url_logs, auth=api_auth, json=api_data_logs)
api_res_logs_json = api_res_logs.json()
# print(api_res_logs_json)

if api_res_logs.status_code != 200:
    raise Exception("Can't create log listener, code \"{} ({})\"!".format(api_res_logs_json['code'], api_res_logs_json['status']))

ws_url_logs = "{}?token={}".format(api_res_logs_json['url'], api_res_logs_json['token'])



#
# HISTORY LOGS
#

# read last timestamp from historical logs
history_logs_last_timestamp = [None]
def history_logs_on_message(ws, message):
    msg_match = re.match(log_re_pattern, message)
    if not msg_match:
        raise Exception("Failed to read log history, regex does not match!")
    history_logs_last_timestamp[0] = parse(msg_match.group(2)).replace(tzinfo=None)

def history_logs_on_error(ws, error):
    print("### history logs error ###")
    raise Exception(error)

history_logs_ws = websocket.WebSocketApp(ws_url_logs,
    on_message = history_logs_on_message,
    header = ws_auth_header)
history_logs_ws.run_forever()
history_logs_last_timestamp = history_logs_last_timestamp[0]

# todo: can logs be empty if service is new? (set to some minutes ago)
if history_logs_last_timestamp == None:
    raise Exception("Failed to read last log timestamp!")

print("Last historical timestamp: {}".format(history_logs_last_timestamp))

if log_handler.has_error == True:
    raise Exception(log_handler.last_error)
log_handler.clear()



#
# EVENT LISTENER
#

# first we read container info (start-count) so we know if we're dealing with old events or not...
api_url_info = "{}/containers/{}".format(api_base_url, node_id)
api_res_info = requests.get(api_url_info, auth=api_auth)
api_res_info_json = api_res_info.json()
old_container_start_count = api_res_info_json['startCount']
# print(json.dumps(api_res_info_json, indent=2))

if api_res_info.status_code != 200:
    raise Exception("Can't read container information, code \"{} ({})\"!".format(api_res_info_json['code'], api_res_info_json['status']))


def events_on_open(ws):
    print("### events stream opened ###")
    # tell the service to start before attaching log listener
    api_url_start = "{}/containers/{}?action=start".format(api_base_url, node_id)
    api_res_start = requests.post(api_url_start, auth=api_auth)
    api_res_start_json = api_res_start.json()

    if not api_res_start.status_code < 300:
        raise Exception("Can't start service, code \"{} ({})\"!".format(api_res_start_json['code'], api_res_start_json['status']))

def events_on_message(ws, message):
    json_message = json.loads(message)
    if "resourceId" not in json_message or json_message["resourceId"] != node_id:
        return
    # is this an old event?
    new_container_start_count = json_message["data"]["resource"]["startCount"]
    if new_container_start_count <= old_container_start_count:
        return
    node_state = json_message["data"]["resource"]["state"]
    print("Container state: {}".format(node_state))
    if node_state in ["running", "stopping", "stopped"]:
        ws.close()

ws_base_url = api_base_url.replace("https:", "wss:").replace("http:", "ws:")

ws_url_events = "{}/projects/{}/subscribe?eventNames=resource.change".format(ws_base_url, environment_id)
ws_events = websocket.WebSocketApp(ws_url_events,
    on_open = events_on_open,
    on_message = events_on_message,
    header = ws_auth_header)
ws_events.run_forever()

if log_handler.has_error == True:
    raise Exception(log_handler.last_error)
log_handler.clear()




#
# LOG LISTENER
#
def logs_on_message(ws, message):
    msg_match = re.match(log_re_pattern, message)
    if not msg_match:
        raise Exception("Failed to read log format, regex does not match!")

    is_error = (int(msg_match.group(1)) == 2)
    log_date = parse(msg_match.group(2)).replace(tzinfo=None)
    log_message = msg_match.group(3)
    # print("{} - {}".format(log_date, log_message))

    if log_date > history_logs_last_timestamp:
        if is_error:
            raise Exception(log_message)

        print(log_message)

ws_logs = websocket.WebSocketApp(ws_url_logs,
    on_message = logs_on_message,
    header = ws_auth_header)
ws_logs.run_forever()

if log_handler.has_error == True:
    raise Exception(log_handler.last_error)
log_handler.clear()
