import os
import sys
import json
import random
import argparse
from datetime import datetime

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

interdiction_probability = 0.25
interdiction_duration = (1, 2)

necessity_probability = 0.25
necessity_size = (1, 2)
necessity_start = (1, 3)
necessity_duration = (1, 7)

patient_protocol = (1, 2)
protocol_frequency = (2, 7)
protocol_tolerance = (0, 2)
protocol_start = (1, 10)
protocol_duration = (10, 30)

iteration_size = (1, 3)
iteration_number = (1, 2)
iteration_shift = (-10, 10)

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
        operators[f"{day_index}"] = {}
        for care_unit_index in range(care_unit_number):
            operators[f"{day_index}"][f"cu{care_unit_index:02}"] = {}
            size = random.randint(care_unit_size[0], care_unit_size[1])
            for operator_index in range(size):
                operators[f"{day_index}"][f"cu{care_unit_index:02}"][f"op{operator_index:02}"] = {
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
        requests[f"{day_index}"] = {}
        request_number = random.randint(request_amount[0], request_amount[1])
        patient_indexes = random.sample(range(patient_number), request_number)
        for patient_index in sorted(patient_indexes):
            size = random.randint(request_size[0], request_size[1])
            packets_indexes = random.sample(range(packet_number), size)
            requests[f"{day_index}"][f"pat{patient_index:02}"] = {
                "packets": sorted(map(lambda p: f"pkt{p:02}", packets_indexes))
            }
    return requests

def generate_timestamp():
    timestamp = datetime.now().strftime("%a-%d-%b-%Y-%H-%M-%S")
    return timestamp

def generate_total_care_units_duration(operators):
    total_care_units_duration = dict()
    for day_name, day in operators.items():
        daily_total_care_units_duration = dict()
        for care_unit_name, care_unit in day.items():
            total_care_unit_duration = 0
            for operator in care_unit.values():
                total_care_unit_duration += operator['duration']
            daily_total_care_units_duration[care_unit_name] = total_care_unit_duration
        total_care_units_duration[day_name] = daily_total_care_units_duration
    return total_care_units_duration

def generate_care_unit_names():
    care_unit_names = []
    for care_unit_index in range(care_unit_number):
        care_unit_names.append(f"cu{care_unit_index:02}")
    return care_unit_names

def generate_interdictions():
    interdictions = dict()
    for service_index in range(service_number):
        service_interdictions = dict()
        for other_service_index in range(service_number):
            if random.random() >= interdiction_probability:
                service_interdictions[f"srv{other_service_index:02}"] = 0
                continue
            service_interdictions[f"srv{other_service_index:02}"] = random.randint(interdiction_duration[0], interdiction_duration[1])
        interdictions[f"srv{service_index:02}"] = service_interdictions
    return interdictions

def generate_necessities():
    necessities = dict()
    for service_index in range(service_number):
        if random.random() >= necessity_probability:
            necessities[f"srv{service_index:02}"] = dict()
            continue
        necessity_amount = random.randint(necessity_size[0], necessity_size[1])
        service_indexes = random.sample(range(service_number), necessity_amount)
        service_necessities = dict()
        for other_service_index in sorted(service_indexes):
            if other_service_index == service_index:
                continue
            start = random.randint(necessity_start[0], necessity_start[1])
            duration = random.randint(necessity_duration[0], necessity_duration[1])
            service_necessities[f"srv{other_service_index:02}"] = [
                start,
                start + duration
            ]
        necessities[f"srv{service_index:02}"] = service_necessities
    return necessities

def generate_patients():
    patients = dict()
    protocol_index = 0
    for patient_index in range(patient_number):
        patient = dict()
        protocol_number = random.randint(patient_protocol[0], patient_protocol[1])
        for _ in range(protocol_number):
            protocol = dict()
            iteration = []
            packet_amount = random.randint(iteration_size[0], iteration_size[1])
            packet_indexes = random.sample(range(packet_number), packet_amount)
            for packet_index in sorted(packet_indexes):
                existence_start = random.randint(protocol_start[0], protocol_start[1])
                existence_duration = random.randint(protocol_duration[0], protocol_duration[1])
                iteration.append({
                    'packet_id': f"pkt{packet_index:02}",
                    'start_date': random.randint(existence_start, existence_start + existence_duration),
                    'freq': random.randint(protocol_frequency[0], protocol_frequency[1]),
                    'since': "start_date",
                    'tolerance': random.randint(protocol_tolerance[0], protocol_tolerance[1]),
                    'existence': [
                        existence_start,
                        existence_start + existence_duration
                    ]
                })
            iteration_amount = random.randint(iteration_number[0], iteration_number[1])
            for interation_index in range(iteration_amount):
                initial_shift = random.randint(iteration_shift[0], iteration_shift[1])
                protocol[f"iter{interation_index:02}"] = [
                    iteration,
                    initial_shift
                ]
            patient[f"prot{protocol_index:02}"] = protocol
        patient['priority_weight'] = random.randint(patient_priority[0], patient_priority[1])
        patients[f"pat{patient_index:02}"] = patient
    return patients

def generate_full_input(operators, services, packets):
            timestamp = generate_timestamp()
            care_unit_names = generate_care_unit_names()
            total_care_units_duration = generate_total_care_units_duration(operators)
            interdictions = generate_interdictions()
            necessities = generate_necessities()
            patients = generate_patients()
            full_input = {
                'datecode' : timestamp,
                'horizon': day_number,
                'resources': care_unit_names,
                'capacity' : total_care_units_duration,
                'daily_capacity' : operators,
                'services': services,
                'interdiction': interdictions,
                'necessity': necessities,
                'abstract_packet': packets,
                'pat_request': patients
            }
            return full_input

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
    parser.add_argument("--only-requests", action="store_true", help="don't generate the protocol input")
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

        services = generate_services()
        packets = generate_packets()
        operators = generate_operators()
        priorities = generate_priorities()
        if args.only_requests:
            requests = generate_requests()
        else:
            full_input = generate_full_input(operators, services, packets)

        with open("services.json", "w") as f:
            json.dump(services, f, indent=4)
        with open("packets.json", "w") as f:
            json.dump(packets, f, indent=4)
        with open("operators.json", "w") as f:
            json.dump(operators, f, indent=4)
        with open("priorities.json", "w") as f:
            json.dump(priorities, f, indent=4)
        if args.only_requests:
            with open("requests.json", "w") as f:
                json.dump(requests, f, indent=4)
            if os.path.isfile("full_input.json"):
                os.remove("full_input.json")
        else:
            with open("full_input.json", "w") as f:
                json.dump(full_input, f, indent=4)
            if os.path.isfile("requests.json"):
                os.remove("requests.json")
        if os.path.isfile("subsumptions.json"):
            os.remove("subsumptions.json")
        if os.path.isfile("results.json"):
            os.remove("results.json")
        if os.path.isfile("cores.json"):
            os.remove("cores.json")
        if args.verbose:
            print(f"Created instance '{args.prefix}{instance_index:02}'")
        os.chdir("..")

    if args.verbose:
        print(f"Generated {args.number} instance(s)")