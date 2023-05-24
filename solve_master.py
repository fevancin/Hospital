import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

from pyomo.environ import ConcreteModel, SolverFactory, maximize, TerminationCondition
from pyomo.environ import Set, Var, Objective, Constraint, ConstraintList
from pyomo.environ import Boolean, value

asp_program = """
% patient_requests_protocol(Patient, Protocol, Iteration, Packet, StartDay, ExistenceStart, ExistenceEnd, Frequency, Tolerance).
% patient_has_priority(Patient, Priority).
% service(Service, CareUnit, Duration).
% packet_has_service(Packet, Service).
% care_unit_has_daily_capacity(CareUnit, Day, Capacity).
% service_is_incompatible_with(Service1, Service2, DayWindow).
% service_has_necessity_of(Service1, Service2, WindowStart, WindowEnd).
% day(0..N).

{ do(Patient, Packet, Day) } :-
    patient_requests_protocol(Patient, _, _, Packet, StartDay, ExistenceStart, ExistenceEnd, Frequency, Tolerance),
    day(Day), Day >= ExistenceStart, Day <= ExistenceEnd,
    (Day - StartDay + Tolerance) \ Frequency <= (Tolerance * 2).

protocol_window_done(Patient, Protocol, Iteration, 1..N, Packet) :-
    patient_requests_protocol(Patient, Protocol, Iteration, Packet, StartDay, ExistenceStart, ExistenceEnd, Frequency, _),
    N = (ExistenceEnd - StartDay + 1) / Frequency.

% protocol_iteration_packet_done(Patient, Protocol, Iteration, Packet) :-
%     patient_requests_protocol(Patient, Protocol, Iteration, Packet, StartDay, ExistenceStart, ExistenceEnd, Frequency, Tolerance),

% :- care_unit_has_daily_capacity(CareUnit, Day, Capacity),
%     #sum { Duration,Patient,Service :
%         do(Patient, Packet, Day),
%         packet_has_service(Packet, Service),
%         service(Service, CareUnit, Duration) } > Capacity.

% :- do(Patient, Packet1, Day1), do(Patient, Packet2, Day2),
%     packet_has_service(Packet1, Service1), packet_has_service(Packet2, Service2),
%     service_is_incompatible_with(Service1, Service2, DayWindow),
%     Day2 - Day1 < DayWindow.

% :- do(Patient, Packet1, Day1), not do(Patient, Packet2, Day2), day(Day2),
%     packet_has_service(Packet1, Service1), packet_has_service(Packet2, Service2),
%     service_has_necessity_of(Service1, Service2, WindowStart, WindowEnd),
%     % Day2 >= Day1, maybe implied by the next two..
%     Day2 - Day1 >= WindowStart, Day2 - Day1 <= WindowEnd.

:~ do(Patient, Packet, Day), patient_has_priority(Patient, Priority). [-1@Priority,Patient,Packet,Day]

#show do/3.
"""

def solve_master_with_asp(full_input):

    patient_names = set()
    service_names = set()
    packet_names = set()
    care_unit_names = set()

    with open("input.lp", "w") as f:
        for patient_name, patient in full_input['pat_request'].items():
            patient_names.add(patient_name)
            for protocol_name, protocol in patient.items():
                if protocol_name == "priority_weight":
                    continue
                for iteration_name, iteration in protocol.items():
                    initial_offset = iteration[1]
                    for protocol_packet in iteration[0]:
                        packet_name = protocol_packet['packet_id']
                        packet_names.add(packet_name)
                        for service_name in full_input['abstract_packet'][packet_name]:
                            service_names.add(service_name)
                            care_unit_names.add(full_input['services'][service_name]['careUnit'])
                        f.write(f"patient_requests_protocol({patient_name}, {protocol_name}, {iteration_name}, {packet_name}, {protocol_packet['start_date'] + initial_offset}, {protocol_packet['existence'][0] + initial_offset}, {protocol_packet['existence'][1] + initial_offset}, {protocol_packet['freq']}, {protocol_packet['tolerance']}).\n")

    patient_names = sorted(patient_names)
    service_names = sorted(service_names)
    packet_names = sorted(packet_names)
    care_unit_names = sorted(care_unit_names)

    with open("input.lp", "a") as f:
        for patient_name in patient_names:
            f.write(f"patient_has_priority({patient_name}, {full_input['pat_request'][patient_name]['priority_weight']}).\n")

    with open("input.lp", "a") as f:
        for service_name in service_names:
            f.write(f"service({service_name}, {full_input['services'][service_name]['careUnit']}, {full_input['services'][service_name]['duration']}).\n")

    with open("input.lp", "a") as f:
        for packet_name in packet_names:
            for service_name in full_input['abstract_packet'][packet_name]:
                f.write(f"packet_has_service({packet_name}, {service_name}).\n")

    with open("input.lp", "a") as f:
        for day_name, day in full_input['capacity'].items():
            for care_unit_name in care_unit_names:
                f.write(f"care_unit_has_daily_capacity({care_unit_name}, {int(day_name)}, {day[care_unit_name]}).\n")

    with open("input.lp", "a") as f:
        for service_name in service_names:
            for other_service_name, duration in full_input['interdiction'][service_name].items():
                if duration == 0 or other_service_name not in service_names:
                    continue
                f.write(f"service_is_incompatible_with({service_name}, {other_service_name}, {duration}).\n")

    with open("input.lp", "a") as f:
        for service_name in service_names:
            for other_service_name, window in full_input['necessity'][service_name].items():
                f.write(f"service_has_necessity_of({service_name}, {other_service_name}, {window[0]}, {window[1]}).\n")

    with open("input.lp", "a") as f:
        f.write(f"day(0..{full_input['horizon'] - 1}).\n")
    
    with open("program.lp", "w") as f:
        f.write(asp_program)

    with open("output.txt", "w") as f:
        subprocess.run(["clingo", "input.lp", "program.lp"], stdout=f, stderr=subprocess.DEVNULL)

    requests = dict()
    with open("output.txt", "r") as f:
        rows = f.read().split("Answer")[-1].split("\n")[1].split("do(")[1:]
        rows[-1] += " "
        for row in rows:
            tokens = row.split(",")
            tokens[2] = tokens[2][:-2]
            day_name = f"{int(tokens[2])}"
            if day_name not in requests:
                requests[day_name] = dict()
            if tokens[0] not in requests[day_name]:
                requests[day_name][tokens[0]] = {
                    'packets': []
                }
            requests[day_name][tokens[0]]['packets'].append(tokens[1])
    return requests

def solve_master_with_milp(full_input, use_cores, print_flag=False):
    care_units_touched_by_packet = dict()
    for packet_name, packet in full_input['abstract_packet'].items():
        care_units = set()
        for service_name in packet:
            care_units.add(full_input['services'][service_name]['careUnit'])
        care_units_touched_by_packet[packet_name] = care_units

    x_indexes = set()
    l_indexes = set()
    epsilon_indexes = set()

    x_and_l_indexes = set()
    capacity_indexes = set()
    interdiction_indexes = set()
    necessity_indexes = set()

    for patient_name, patient in full_input['pat_request'].items():
        # patient_priority = patient['priority_weight']
        for protocol_name, protocol in patient.items():
            if protocol_name == "priority_weight":
                continue
            for iteration_name, iteration in protocol.items():
                initial_offset = iteration[1]
                for protocol_packet in iteration[0]:
                    packet_name = protocol_packet['packet_id']
                    for perfect_day in range(protocol_packet['start_date'] + initial_offset, protocol_packet['existence'][1] + initial_offset + 1, protocol_packet['freq']):
                        if perfect_day < protocol_packet['existence'][0] or perfect_day > protocol_packet['existence'][1]:
                            continue
                        there_is_at_least_one_day = False
                        min_day = 10000
                        max_day = -10000
                        for day_name in range(perfect_day - protocol_packet['tolerance'], perfect_day + protocol_packet['tolerance'] + 1):
                            if day_name >= full_input['horizon']:
                                continue
                            if day_name < protocol_packet['existence'][0] or day_name > protocol_packet['existence'][1]:
                                continue
                            is_packet_assignable = True
                            temp_l_indexes = set()
                            for service_name in full_input['abstract_packet'][packet_name]:
                                service_care_unit = full_input['services'][service_name]['careUnit']
                                service_duration = full_input['services'][service_name]['duration']
                                if service_duration > full_input['capacity'][str(day_name)][service_care_unit]:
                                    is_packet_assignable = False
                                    break
                                temp_l_indexes.add((patient_name, service_name, day_name))
                            if is_packet_assignable:
                                x_indexes.add((patient_name, packet_name, day_name))
                                l_indexes.update(temp_l_indexes)
                                for care_unit_name in care_units_touched_by_packet[packet_name]:
                                    capacity_indexes.add((day_name, care_unit_name))
                                for patient_name1, service_name1, day_name1 in temp_l_indexes:
                                    x_and_l_indexes.add((patient_name1, packet_name, service_name1, day_name1))
                                there_is_at_least_one_day = True
                                if day_name < min_day:
                                    min_day = day_name
                                if day_name > max_day:
                                    max_day = day_name
                        if there_is_at_least_one_day:
                            epsilon_indexes.add((patient_name, packet_name, f"{protocol_name}__{iteration_name}__{min_day}__{max_day}"))

    for service_name1, necessities in full_input['necessity'].items():
        for service_name2, times in necessities.items():
            if times[0] - 1 > full_input['interdiction'][service_name1][service_name2]:
                full_input['interdiction'][service_name1][service_name2] = times[0] - 1
            for patient_name3, service_name3, day_name3 in l_indexes:
                    for patient_name4, service_name4, _ in l_indexes:
                        if service_name3 == service_name1 and patient_name3 == patient_name4 and service_name4 == service_name2:
                            necessity_indexes.add((patient_name3, service_name1, service_name2, day_name3))

    for service_name1, interdictions in full_input['interdiction'].items():
        for service_name2, time in interdictions.items():
            if time > 0:
                for patient_name3, service_name3, day_name3 in l_indexes:
                    for patient_name4, service_name4, _ in l_indexes:
                        if service_name3 == service_name1 and patient_name3 == patient_name4 and service_name4 == service_name2:
                            interdiction_indexes.add((patient_name3, service_name1, service_name2, day_name3))

    x_indexes = sorted(x_indexes)
    l_indexes = sorted(l_indexes)
    epsilon_indexes = sorted(epsilon_indexes)
    x_and_l_indexes = sorted(x_and_l_indexes)
    capacity_indexes = sorted(capacity_indexes)
    interdiction_indexes = sorted(interdiction_indexes)
    necessity_indexes = sorted(necessity_indexes)

    model = ConcreteModel()

    model.x_indexes = Set(initialize=x_indexes)
    model.l_indexes = Set(initialize=l_indexes)
    model.epsilon_indexes = Set(initialize=epsilon_indexes)
    model.x_and_l_indexes = Set(initialize=x_and_l_indexes)
    model.capacity_indexes = Set(initialize=capacity_indexes)
    model.interdiction_indexes = Set(initialize=interdiction_indexes)
    model.necessity_indexes = Set(initialize=necessity_indexes)

    del l_indexes, epsilon_indexes, x_and_l_indexes, capacity_indexes, interdiction_indexes, necessity_indexes

    model.x = Var(model.x_indexes, domain=Boolean)
    model.l = Var(model.l_indexes, domain=Boolean)
    model.epsilon = Var(model.epsilon_indexes, domain=Boolean)

    def ff(model):
        return sum(model.epsilon[patient_name, packet_name, window_name] for patient_name, packet_name, window_name in model.epsilon_indexes)
    model.objective = Objective(rule=ff, sense=maximize)

    def f1(model, patient_name, packet_name, service_name, day_name):
        return model.x[patient_name, packet_name, day_name] <= model.l[patient_name, service_name, day_name]
    model.x_and_l = Constraint(model.x_and_l_indexes, rule=f1)

    def f2(model, patient_name, packet_name, window_name):
        _, _, min_day, max_day = window_name.split("__")
        return sum([model.x[patient_name, packet_name, day_name] for day_name in range(int(min_day), int(max_day) + 1) if (patient_name, packet_name, day_name) in model.x]) == model.epsilon[patient_name, packet_name, window_name]
    model.x_and_epsilon = Constraint(model.epsilon_indexes, rule=f2)

    def f3(model, day_name, care_unit_name):
        return (sum([model.l[patient_name, service_name, day_name] * full_input['services'][service_name]['duration']
            for patient_name, service_name, day_name1 in model.l_indexes
            if day_name1 == day_name and full_input['services'][service_name]['careUnit'] == care_unit_name]) <=
            full_input['capacity'][str(day_name)][care_unit_name])
    model.respect_capacity = Constraint(model.capacity_indexes, rule=f3)

    def f4(model, patient_name, service_name1, service_name2, day_name):
        time = full_input['interdiction'][service_name1][service_name2]
        day_names = []
        for day_name2 in range(day_name + 1, day_name + time + 1):
            if (patient_name, service_name2, day_name2) in model.l:
                day_names.append(day_name2)
        if len(day_names) == 0:
            return Constraint.Skip
        return sum([model.l[patient_name, service_name2, day_name2] for day_name2 in day_names]) <= (1 - model.l[patient_name, service_name1, day_name]) * len(day_names)
    model.interdictions = Constraint(model.interdiction_indexes, rule=f4)

    impossible_assignments = set()

    def f5(model, patient_name, service_name1, service_name2, day_name):
        times = full_input['necessity'][service_name1][service_name2]
        day_names = []
        for day_name2 in range(day_name + times[0], day_name + times[1] + 1):
            if (patient_name, service_name2, day_name2) in model.l:
                day_names.append(day_name2)
        if len(day_names) == 0:
            impossible_assignments.add((patient_name, service_name1, day_name))
            return Constraint.Skip
        return sum([model.l[patient_name, service_name2, day_name2] for day_name2 in day_names]) >= model.l[patient_name, service_name1, day_name]
    model.necessities = Constraint(model.necessity_indexes, rule=f5)

    for patient_name, service_name, day_name in impossible_assignments:
        model.l[patient_name, service_name, day_name].fix(0)
        for patient_name1, packet_name, day_name1 in model.x_indexes:
            if patient_name1 == patient_name and day_name1 == day_name and service_name in full_input['abstract_packet'][packet_name]:
                model.x[patient_name, packet_name, day_name].fix(0)

    if use_cores:
        # add core constraints
        model.list = ConstraintList()
        if os.path.isfile("prev_cores.json"):
            with open("prev_cores.json", "r") as f:
                prev_cores = json.load(f)
            for prev_core in prev_cores["list"]:
                indexes = []
                for core_constraint in prev_core:
                    indexes.append((core_constraint[0], core_constraint[1], core_constraint[2]))
                model.list.add(expr=sum(model.l[p, s, int(d)] for (p, s, d) in indexes) <= len(indexes) - 1)
        else:
            prev_cores = {"list": []}
        if os.path.isfile("cores.json"):
            with open("cores.json", "r") as f:
                cores = json.load(f)
            for core in cores.values():
                for day_name in core["days"]:
                    patient_services = dict()
                    for x_index in x_indexes:
                        if x_index[2] != int(day_name):
                            continue
                        if x_index[0] not in patient_services:
                            patient_services[x_index[0]] = set()
                        for service_name in full_input["abstract_packet"][x_index[1]]:
                            patient_services[x_index[0]].add(service_name)
                    for patient_name, service_list in patient_services.items():
                        patient_services[patient_name] = sorted(service_list)
                    who_could_be = []
                    for multipacket_name, multipacket in core["multipackets"].items():
                        patient_list = []
                        for patient_name, service_list in patient_services.items():
                            is_contained = True
                            for service_name in multipacket["services"]:
                                if service_name not in service_list:
                                    is_contained = False
                                    break
                            if is_contained:
                                patient_list.append(patient_name)
                        who_could_be.append({
                            "name": multipacket_name,
                            "patients": patient_list
                        })
                    # who_could_be = [
                    #     {"name": 'srv01_srv05', "patients": ['pat00', 'pat03', 'pat05']},
                    #     {"name": 'srv05', "patients": ['pat00', 'pat01']},
                    #     {"name": 'srv07', "patients": ['pat06', 'pat12', 'pat22']}
                    # ]
                    # print(who_could_be)
                    choice_indexes = []
                    for _ in who_could_be:
                        choice_indexes.append(0)
                    def get_next(value3: list[int]=None):
                        if value3 is None:
                            return [0 for _ in who_could_be]
                        index = 0
                        while index < len(who_could_be):
                            value3[index] += 1
                            if value3[index] < len(who_could_be[index]["patients"]):
                                return value3
                            value3[index] = 0
                            index += 1
                        return None
                    value2 = get_next()
                    while value2 is not None:
                        actual_value = []
                        for value_index in range(len(value2)):
                            actual_value.append(who_could_be[value_index]["patients"][value2[value_index]])
                        # check for repetitions...
                        is_valid_value = len(set(actual_value)) == len(actual_value)
                        if is_valid_value:
                            # add index at the day 'day_name' for patients in the index
                            print(actual_value)
                            expr_indexes = []
                            core_list = []
                            for index in range(len(actual_value)):
                                for service_name in core["multipackets"][who_could_be[index]["name"]]["services"]:
                                    expr_indexes.append((actual_value[index], service_name))
                                    core_list.append([actual_value[index], service_name, day_name])
                            model.list.add(expr=sum(model.l[p, s, int(day_name)] for (p, s) in expr_indexes) <= len(expr_indexes) - 1)
                            prev_cores["list"].append(core_list)
                        value2 = get_next(value2)
            with open("prev_cores.json", "w") as f:
                print("writing")
                print(prev_cores)
                json.dump(prev_cores, f)
            os.remove("cores.json")
    
    if print_flag:
        model.pprint()
    
    opt = SolverFactory('gurobi')
    result = opt.solve(model)

    requests = dict()
    if result.solver.termination_condition == TerminationCondition.infeasible:
        requests = {}
    else:
        for patient_name, packet_name, day_name in model.x_indexes:
            if value(model.x[patient_name, packet_name, day_name]) == 0:
                continue
            if day_name not in requests:
                requests[day_name] = dict()
            if patient_name not in requests[day_name]:
                requests[day_name][patient_name] = {
                    'packets': []
                }
            requests[day_name][patient_name]['packets'].append(packet_name)
    return requests

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Solve master problem instances")
    parser.add_argument("-m", "--method", metavar="MET", type=str, default="asp", choices=["asp", "milp"], help="solution method used (asp|milp)")
    parser.add_argument("-i", "--input", metavar="IN", type=str, default="instances", help="input folder with the instances")
    parser.add_argument("--use-cores", action="store_true", help="core json file")
    parser.add_argument("-v", "--verbose", action="store_true", help="show what is done")
    args = parser.parse_args(sys.argv[1:])

    os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

    if not os.path.isdir(args.input):
        raise FileNotFoundError(f"Input folder '{args.input}' not found")
    os.chdir(args.input)

    instance_number = len(os.listdir("."))
    if instance_number == 0:
        print("No instance folder found. No action taken.")
        exit(0)

    if args.verbose:
        total_time = 0

    for folder_name in sorted(os.listdir(".")):
        os.chdir(folder_name)
        if args.verbose:
            print(f"Read instance '{folder_name}' ... ", end=" ")
        with open("full_input.json", "r") as f:
            full_input = json.load(f)
        if args.verbose:
            start_time = datetime.now()
        if args.method == "asp":
            requests = solve_master_with_asp(full_input)
        elif args.method == "milp":
            print_flag = folder_name == "instance07"
            requests = solve_master_with_milp(full_input, args.use_cores, print_flag)
        if args.verbose:
            end_time = datetime.now()
        with open("requests.json", "w") as f:
            json.dump(requests, f, indent=4, sort_keys=True)
        if args.verbose:
            delta = (end_time - start_time).total_seconds()
            print(f"finished! Time taken: {delta}s")
            total_time += delta
        if os.path.isfile("input.lp"):
            os.remove("input.lp")
        if os.path.isfile("program.lp"):
            os.remove("program.lp")
        if os.path.isfile("output.txt"):
            os.remove("output.txt")
        os.chdir("..")

    if args.verbose:
        print(f"Solved master problem for {instance_number} instance(s). Total time taken: {total_time}s, average: {total_time / instance_number}s")