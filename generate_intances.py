import os
import sys
import json
import random
import argparse

################################################################################
#                            GENERATOR CONFIGURATION                           #
################################################################################

day_number = 30
care_unit_number = 4

service_number = 50
service_duration = (1, 10)
service_cost = (1, 10)

packet_number = 50
packet_size = (1, 3)

operator_start = (1, 50)
operator_duration = (10, 50)
care_unit_size = (1, 4)         # how many operators can be inside one care unit

patient_number = 20
patient_priority = (1, 4)

request_amount = (1, 4)         # patient number in the same day
request_size = (1, 2)           # numer of packets requested by a single patient

################################################################################

def generate_services():
    services = {}
    for service_index in range(service_number):
        services[f"srv{service_index:02}"] = {
            "careUnit": f"cu{random.randint(0, care_unit_number - 1):02}",
            "duration": random.randint(service_duration[0], service_duration[1]),
            "cost": random.randint(service_cost[0], service_cost[1])
        }
    return services

def generate_packets():
    packets = {}
    packet_index = 0
    packet_remaining = packet_number
    size = packet_size[0]
    max_size = packet_size[1]
    while packet_index < packet_number:
        window_size = packet_remaining // 2
        if window_size == 0:
            window_size = 1
        packet_remaining -= window_size
        for _ in range(window_size):
            service_indexes = random.sample(range(service_number), size)
            packets[f"pkt{packet_index:02}"] = sorted(map(lambda s : f"srv{s:02}", service_indexes))
            packet_index += 1
        if size + 1 <= max_size:
            size += 1
    return packets

def generate_operators():
    operators = {}
    for day_index in range(day_number):
        operators[f"day{day_index:02}"] = {}
        for care_unit_index in range(care_unit_number):
            operators[f"day{day_index:02}"][f"cu{care_unit_index:02}"] = {}
            size = random.randint(care_unit_size[0], care_unit_size[1])
            for operator_index in range(size):
                operators[f"day{day_index:02}"][f"cu{care_unit_index:02}"][f"op{operator_index:02}"] = {
                    "start": random.randint(operator_start[0], operator_start[1]),
                    "duration": random.randint(operator_duration[0], operator_duration[1])
                }
    return operators

def generate_priorities():
    priorities = {}
    for patient_index in range(patient_number):
        priorities[f"pat{patient_index:02}"] = random.randint(patient_priority[0], patient_priority[1])
    return priorities

def generate_requests():
    requests = {}
    for day_index in range(day_number):
        requests[f"day{day_index:02}"] = {}
        request_number = random.randint(request_amount[0], request_amount[1])
        patient_indexes = random.sample(range(patient_number), request_number)
        for patient_index in sorted(patient_indexes):
            size = random.randint(request_size[0], request_size[1])
            packets_indexes = random.sample(range(packet_number), size)
            requests[f"day{day_index:02}"][f"pat{patient_index:02}"] = {
                "packets": sorted(map(lambda p: f"pkt{p:02}", packets_indexes))
            }
    return requests

if __name__ == "__main__":

    def check_number(n: str):
        if not n.isnumeric() or int(n) <= 0 or int(n) > 100:
            raise argparse.ArgumentTypeError("Number must be an integer between 1 and 100")
        return n

    parser = argparse.ArgumentParser(description="Generate one or more instance for the subproblem")
    parser.add_argument("-s", "--seed", metavar="SEED", type=int, default=42, help="seed fo the random generator")
    parser.add_argument("-n", "--number", metavar="NUM", type=check_number, default=1, help="number of instance to generate")
    parser.add_argument("-p", "--prefix", metavar="PRE", type=str, default="instance", help="prefix for the generated folder(s)")
    parser.add_argument("-o", "--output", metavar="OUT", type=str, default="instances", help="destination folder for the output")
    parser.add_argument("-v", "--verbose", action="store_true", help="show what is done")
    args = parser.parse_args(sys.argv[1:])

    os.chdir(os.path.dirname(sys.argv[0]))

    if not os.path.isdir(args.output):
        os.mkdir(args.output)
        if args.verbose:
            print(f"Created the '{args.output}' folder containing all instances")
    os.chdir(args.output)

    for instance_index in range(int(args.number)):
        if not os.path.isdir(f"{args.prefix}{instance_index:02}"):
            os.mkdir(f"{args.prefix}{instance_index:02}")
            if args.verbose:
                print(f"Created the folder '{args.prefix}{instance_index:02}'", end=" ")
        os.chdir(f"{args.prefix}{instance_index:02}")
        with open("services.json", "w") as f:
            json.dump(generate_services(), f, indent=4)
        with open("packets.json", "w") as f:
            json.dump(generate_packets(), f, indent=4)
        with open("operators.json", "w") as f:
            json.dump(generate_operators(), f, indent=4)
        with open("priorities.json", "w") as f:
            json.dump(generate_priorities(), f, indent=4)
        with open("requests.json", "w") as f:
            json.dump(generate_requests(), f, indent=4)
        if args.verbose:
            print(f"Created instance '{args.prefix}{instance_index:02}'")
        os.chdir("..")

    if args.verbose:
        print(f"Generated {args.number} instance(s)")