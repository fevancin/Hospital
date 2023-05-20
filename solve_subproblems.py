import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

from pyomo.environ import ConcreteModel, SolverFactory, maximize, TerminationCondition
from pyomo.environ import Set, Var, Objective, Constraint
from pyomo.environ import Boolean, NonNegativeIntegers, value

asp_program = """
% variable for the assignment of services
{ do(Patient, Service, Operator, CareUnit, Time) } :-
    patient_requests_packet(Patient, Packet),                       % the patient must request a packet..
    packet_has_service(Packet, Service),                            % ..that contains a service..
    service(Service, CareUnit, ServiceDuration),                    % ..of the care unit..
    operator(Operator, CareUnit, OperatorStart, OperatorDuration),  % ..that is the same of the operator.
    ServiceDuration <= OperatorDuration,                            % service must be satisfiable.
    Time >= OperatorStart,                                          % the operator interval must be respected.
    Time + ServiceDuration <= OperatorStart + OperatorDuration,
    time(Time).

% a service cannot be satisfied more than once
:- patient_requests_packet(Patient, Packet), packet_has_service(Packet, Service),
    #count { Operator,CareUnit,Time : do(Patient, Service, Operator, CareUnit, Time) } > 1.

% the same patient cannot be in two places at the same time
:- do(Patient, Service1, _, _, Time1), do(Patient, Service2, _, _, Time2),
    Service1 != Service2,
    service(Service1, _, ServiceDuration1),
    Time1 <= Time2, Time1 + ServiceDuration1 > Time2.

% the same operator cannot satisfy two requests if they overlap in time
:- do(Patient1, Service1, Operator, CareUnit, Time1), do(Patient2, Service2, Operator, CareUnit, Time2),
    #count { p : Patient1 == Patient2 ; s : Service1 == Service2 } 1, % the patient or the service can be the same, but not both at the same time
    service(Service1, _, ServiceDuration1),
    Time1 <= Time2, Time1 + ServiceDuration1 > Time2.

% true if the entire packet is satisfied
{ packet_done(Patient, Packet) } :- patient_requests_packet(Patient, Packet).

% a packet must be satisfied in its entirety
:- packet_done(Patient, Packet), packet_has_service(Packet, Service), not do(Patient, Service, _, _, _).

% every service must be linked with at least one satisfied packets (no useless services)
:- do(Patient, Service, _, _, _), #count { Packet : packet_has_service(Packet, Service), packet_done(Patient, Packet) } = 0.

% try to maximize the number of packets done, weighted by the patient priority
:~ packet_done(Patient, Packet), patient_has_priority(Patient, Priority). [-10@Priority,Patient,Packet]

#show do/5.
"""

def solve_day_with_asp(day_name, services, packets, operators, priorities, requests):

    daily_requests = requests[day_name]

    if len(daily_requests) == 0:
        return []
    
    # accumulators for each necessary name (no useless info in the input ASP file)
    patient_names = set()
    service_names = set()
    packet_names = set()
    care_unit_names = set()

    with open("input.lp", "w") as f:
        for patient_name, patient in daily_requests.items():
            patient_names.add(patient_name)
            for packet_name in patient['packets']:
                packet_names.add(packet_name)
                for service_name in packets[packet_name]:
                    service_names.add(service_name)
                    care_unit_names.add(services[service_name]['careUnit'])
                f.write(f"patient_requests_packet({patient_name}, {packet_name}).\n")

    patient_names = sorted(patient_names)
    service_names = sorted(service_names)
    packet_names = sorted(packet_names)
    care_unit_names = sorted(care_unit_names)

    with open("input.lp", "a") as f:
        for patient_name in patient_names:
            f.write(f"patient_has_priority({patient_name}, {priorities[patient_name]}).\n")

    with open("input.lp", "a") as f:
        for service_name in service_names:
            f.write(f"service({service_name}, {services[service_name]['careUnit']}, {services[service_name]['duration']}).\n")

    with open("input.lp", "a") as f:
        for packet_name in packet_names:
            for service_name in packets[packet_name]:
                f.write(f"packet_has_service({packet_name}, {service_name}).\n")

    max_time = 0

    with open("input.lp", "a") as f:
        for care_unit_name in care_unit_names:
            for operator_name, operator in operators[day_name][care_unit_name].items():
                if operator['start'] + operator['duration'] > max_time:
                    max_time = operator['start'] + operator['duration']
                f.write(f"operator({operator_name}, {care_unit_name}, {operator['start']}, {operator['duration']}).\n")

    with open("input.lp", "a") as f:
        f.write(f"time(0..{max_time - 1}).\n")
    
    with open("program.lp", "w") as f:
        f.write(asp_program)

    # solve subproblem problem
    with open("output.txt", "w") as f:
        subprocess.run(["clingo", "input.lp", "program.lp"], stdout=f, stderr=subprocess.DEVNULL)

    # decoding solver answer
    daily_scheduled_services = []
    with open("output.txt", "r") as f:
        rows = f.read().split("Answer")[-1].split("\n")[1].split("do(")[1:]
        if len(rows) > 0:
            rows[-1] += " "
            for row in rows:
                tokens = row.split(",")
                tokens[4] = tokens[4][:-2]
                daily_scheduled_services.append({
                    'patient': tokens[0],
                    'service': tokens[1],
                    'operator': tokens[2],
                    'care_unit': tokens[3],
                    'start': int(tokens[4])
                })
    return daily_scheduled_services

def solve_day_with_milp(day_name, services, packets, operators, priorities, requests, method):

    # accumulators for each necessary index (no useless info)
    x_indexes = set()
    chi_indexes = set()
    packet_indexes = set()
    packet_consistency_indexes = set()
    aux1_indexes = set()
    aux2_indexes = set()
    max_times = dict()

    for care_unit_name, care_unit in operators[day_name].items():
        max_time = 0
        for operator in care_unit.values():
            end_time = operator["start"] + operator["duration"]
            if end_time > max_time:
                max_time = end_time
        max_times[care_unit_name] = max_time

    daily_requests = requests[day_name]

    if len(daily_requests) == 0:
        return []

    for patient_name, patient in daily_requests.items():
        for packet_name in patient["packets"]:
            is_packet_satisfiable = True
            temp_x_indexes = set()
            temp_chi_indexes = set()
            for service_name in packets[packet_name]:
                is_service_satisfiable = False
                care_unit_name = services[service_name]["careUnit"]
                service_duration = services[service_name]["duration"]
                for operator_name, operator in operators[day_name][care_unit_name].items():
                    if service_duration <= operator["duration"]:
                        is_service_satisfiable = True
                        temp_chi_indexes.add((patient_name, service_name, f"{operator_name}__{care_unit_name}"))
                if not is_service_satisfiable:
                    is_packet_satisfiable = False
                    break
                temp_x_indexes.add((patient_name, service_name))
            if is_packet_satisfiable:
                x_indexes.update(temp_x_indexes)
                chi_indexes.update(temp_chi_indexes)
                packet_indexes.add((patient_name, packet_name))
    
    if len(packet_indexes) == 0:
        return []

    for packet_index in packet_indexes:
        for service_name in packets[packet_index[1]]:
            packet_consistency_indexes.add((packet_index[0], packet_index[1], service_name))
    
    x_indexes = sorted(x_indexes)
    chi_indexes = sorted(chi_indexes)
    packet_indexes = sorted(packet_indexes)
    packet_consistency_indexes = sorted(packet_consistency_indexes)

    for index1 in range(len(x_indexes) - 1):
        for index2 in range(index1 + 1, len(x_indexes)):
            if x_indexes[index1][0] == x_indexes[index2][0]:
                aux1_indexes.add((x_indexes[index1][0], x_indexes[index1][1], x_indexes[index2][1]))
    
    for index1 in range(len(chi_indexes) - 1):
        for index2 in range(index1 + 1, len(chi_indexes)):
            if chi_indexes[index1][2] == chi_indexes[index2][2]:
                if method == "milp_basic" or method == "milp_epsilon":
                    aux2_indexes.add((chi_indexes[index1][2], chi_indexes[index1][0], chi_indexes[index1][1], chi_indexes[index2][0], chi_indexes[index2][1]))
                elif method == "milp_optimized":
                    aux2_indexes.add((chi_indexes[index1][2], chi_indexes[index1][0], chi_indexes[index1][1], chi_indexes[index2][0], chi_indexes[index2][1], 0))
                    aux2_indexes.add((chi_indexes[index1][2], chi_indexes[index1][0], chi_indexes[index1][1], chi_indexes[index2][0], chi_indexes[index2][1], 1))

    aux1_indexes = sorted(aux1_indexes)
    aux2_indexes = sorted(aux2_indexes)

    # solve subproblem problem
    model = ConcreteModel()

    model.x_indexes = Set(initialize=x_indexes)
    model.chi_indexes = Set(initialize=chi_indexes)
    model.packet_indexes = Set(initialize=packet_indexes)
    model.packet_consistency_indexes = Set(initialize=packet_consistency_indexes)
    model.aux1_indexes = Set(initialize=aux1_indexes)
    model.aux2_indexes = Set(initialize=aux2_indexes)

    del x_indexes, chi_indexes, packet_indexes, packet_consistency_indexes, aux1_indexes, aux2_indexes

    model.x = Var(model.x_indexes, domain=Boolean)
    model.t = Var(model.x_indexes, domain=NonNegativeIntegers)
    model.chi = Var(model.chi_indexes, domain=Boolean)
    model.packet = Var(model.packet_indexes, domain=Boolean)
    model.aux1 = Var(model.aux1_indexes, domain=Boolean)
    model.aux2 = Var(model.aux2_indexes, domain=Boolean)

    if method == "milp_epsilon":
        model.epsilon1 = Var(model.aux2_indexes, domain=Boolean)
        model.epsilon2 = Var(model.aux2_indexes, domain=Boolean)

    def f(model):
        return sum(model.packet[patient_name, packet_name] * priorities[patient_name] for patient_name, packet_name in model.packet_indexes)
    model.objective = Objective(rule=f, sense=maximize)

    def f1(model, patient_name, service_name):
        return model.t[patient_name, service_name] <= model.x[patient_name, service_name] * max_times[services[service_name]["careUnit"]]
    model.t_and_x = Constraint(model.x_indexes, rule=f1)

    def f2(model, patient_name, service_name):
        return model.t[patient_name, service_name] >= model.x[patient_name, service_name]
    model.x_and_t = Constraint(model.x_indexes, rule=f2)

    def f3(model, patient_name, service_name):
        return sum(model.chi[p, s, o] for p, s, o in model.chi_indexes if patient_name == p and service_name == s) == model.x[patient_name, service_name]
    model.x_and_chi = Constraint(model.x_indexes, rule=f3)

    def f4(model, patient_name, service_name, compound_name):
        operator_name, care_unit_name = compound_name.split("__")
        start = operators[day_name][care_unit_name][operator_name]["start"]
        return start * model.chi[patient_name, service_name, compound_name] <= model.t[patient_name, service_name]
    model.respect_start = Constraint(model.chi_indexes, rule=f4)

    def f5(model, patient_name, service_name, compound_name):
        operator_name, care_unit_name = compound_name.split("__")
        start = operators[day_name][care_unit_name][operator_name]["start"]
        end = start + operators[day_name][care_unit_name][operator_name]["duration"]
        service_duration = services[service_name]["duration"]
        return model.t[patient_name, service_name] <= (end - service_duration) + (1 - model.chi[patient_name, service_name, compound_name]) * max_times[care_unit_name]
    model.respect_end = Constraint(model.chi_indexes, rule=f5)

    def f6(model, patient_name, packet_name, service_name):
        return model.packet[patient_name, packet_name] <= model.x[patient_name, service_name]
    model.packet_consistency = Constraint(model.packet_consistency_indexes, rule=f6)

    def f7(model, patient_name, service_name1, service_name2):
        service_duration = services[service_name1]["duration"]
        return (model.t[patient_name, service_name1] + service_duration * model.x[patient_name, service_name1] <= model.t[patient_name, service_name2] +
            (1 - model.aux1[patient_name, service_name1, service_name2]) * max_times[services[service_name1]["careUnit"]])
    model.patient_not_overlaps1 = Constraint(model.aux1_indexes, rule=f7)

    def f8(model, patient_name, service_name1, service_name2):
        service_duration = services[service_name2]["duration"]
        return (model.t[patient_name, service_name2] + service_duration * model.x[patient_name, service_name2] <= model.t[patient_name, service_name1] +
            model.aux1[patient_name, service_name1, service_name2] * max_times[services[service_name2]["careUnit"]])
    model.patient_not_overlaps2 = Constraint(model.aux1_indexes, rule=f8)

    if method == "milp_basic":
        def f9(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            service_duration = services[service_name1]["duration"]
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name1, service_name1] + service_duration * model.chi[patient_name1, service_name1, operator_name] <= model.t[patient_name2, service_name2] +
                (1 - model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2]) * max_times[care_unit_name])
        model.operator_not_overlaps1 = Constraint(model.aux2_indexes, rule=f9)

        def f10(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            service_duration = services[service_name2]["duration"]
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name2, service_name2] + service_duration * model.chi[patient_name2, service_name2, operator_name] <= model.t[patient_name1, service_name1] +
                model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2] * max_times[care_unit_name])
        model.operator_not_overlaps2 = Constraint(model.aux2_indexes, rule=f10)
    elif method == "milp_optimized":
        def f9(model, operator_name, patient_name1, service_name1, patient_name2, service_name2, n):
            if n != 0: return Constraint.Skip
            service_duration = services[service_name1]["duration"]
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name1, service_name1] + service_duration * model.chi[patient_name1, service_name1, operator_name] <= model.t[patient_name2, service_name2] +
                (1 - model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 0]) * max_times[care_unit_name])
        model.operator_not_overlaps1 = Constraint(model.aux2_indexes, rule=f9)

        def f10(model, operator_name, patient_name1, service_name1, patient_name2, service_name2, n):
            if n != 1: return Constraint.Skip
            service_duration = services[service_name2]["duration"]
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name2, service_name2] + service_duration * model.chi[patient_name2, service_name2, operator_name] <= model.t[patient_name1, service_name1] +
                model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 1] * max_times[care_unit_name])
        model.operator_not_overlaps2 = Constraint(model.aux2_indexes, rule=f10)

        def f11(model, operator_name, patient_name1, service_name1, patient_name2, service_name2, n):
            if n != 0: return Constraint.Skip
            return (model.chi[patient_name1, service_name1, operator_name] + model.chi[patient_name2, service_name2, operator_name] - 1 <=
                model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 0] + model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 1])
        model.aux_constraints1 = Constraint(model.aux2_indexes, rule=f11)

        def f12(model, operator_name, patient_name1, service_name1, patient_name2, service_name2, n):
            if n == 1:
                return (model.chi[patient_name1, service_name1, operator_name] >=
                    model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 0] + model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 1])
            return (model.chi[patient_name2, service_name2, operator_name] >=
                model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 0] + model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2, 1])
        model.aux_constraints2 = Constraint(model.aux2_indexes, rule=f12)
    elif method == "milp_epsilon":
        def f9(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            service_duration = services[service_name1]['duration']
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name1, service_name1] +
                service_duration * (model.chi[patient_name1, service_name1, operator_name] - model.epsilon1[operator_name, patient_name1, service_name1, patient_name2, service_name2]) <=
                model.t[patient_name2, service_name2] +
                (1 - model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2]) * max_times[care_unit_name])
        model.operator_not_overlaps1 = Constraint(model.aux2_indexes, rule=f9)

        def f10(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            service_duration = services[service_name2]['duration']
            _, care_unit_name = operator_name.split("__")
            return (model.t[patient_name2, service_name2] +
                service_duration * (model.chi[patient_name1, service_name1, operator_name] - model.epsilon2[operator_name, patient_name1, service_name1, patient_name2, service_name2]) <=
                model.t[patient_name1, service_name1] +
                model.aux2[operator_name, patient_name1, service_name1, patient_name2, service_name2] * max_times[care_unit_name])
        model.operator_not_overlaps2 = Constraint(model.aux2_indexes, rule=f10)

        def f11(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon1[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= model.chi[patient_name1, service_name1, operator_name]
        model.ff1 = Constraint(model.aux2_indexes, rule=f11)

        def f12(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon1[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= 1 - model.chi[patient_name2, service_name2, operator_name]
        model.ff2 = Constraint(model.aux2_indexes, rule=f12)

        def f13(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon1[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= model.x[patient_name2, service_name2]
        model.ff3 = Constraint(model.aux2_indexes, rule=f13)

        def f14(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon2[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= model.chi[patient_name2, service_name2, operator_name]
        model.ff4 = Constraint(model.aux2_indexes, rule=f14)

        def f15(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon2[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= 1 - model.chi[patient_name1, service_name1, operator_name]
        model.ff5 = Constraint(model.aux2_indexes, rule=f15)

        def f16(model, operator_name, patient_name1, service_name1, patient_name2, service_name2):
            return model.epsilon2[operator_name, patient_name1, service_name1, patient_name2, service_name2] <= model.x[patient_name1, service_name1]
        model.ff6 = Constraint(model.aux2_indexes, rule=f16)

    # if day_name == "day27":
    #     model.pprint()

    opt = SolverFactory("gurobi")
    result = opt.solve(model)

    # decoding solver answer
    if result.solver.termination_condition == TerminationCondition.infeasible:
        return []

    daily_scheduled_services = []
    for patient_name, service_name, compound_name in model.chi_indexes:
        if value(model.chi[patient_name, service_name, compound_name]):
            operator_name, care_unit_name = compound_name.split("__")
            daily_scheduled_services.append({
                "patient": patient_name,
                "service": service_name,
                "operator": operator_name,
                "care_unit": care_unit_name,
                "start": int(value(model.t[patient_name, service_name]))
            })
    return daily_scheduled_services

def solve_subproblem(services, packets, operators, priorities, requests, method, verbose):
    results = dict()
    for day_name in requests.keys():

        if verbose and method != "asp":
            print(f"{day_name}", end=", ")

        if method == "asp":
            daily_scheduled_services = solve_day_with_asp(day_name, services, packets, operators, priorities, requests)
        else:
            daily_scheduled_services = solve_day_with_milp(day_name, services, packets, operators, priorities, requests, method)
        
        # list all not satisfied packets
        not_scheduled_packets = dict()
        for patient_name, patient in requests[day_name].items():
            for packet_name in patient["packets"]:
                is_packet_satisfied = True
                for service_name in packets[packet_name]:
                    is_service_done = False
                    for scheduled_service in daily_scheduled_services:
                        if scheduled_service["patient"] == patient_name and scheduled_service["service"] == service_name:
                            is_service_done = True
                            break
                    if not is_service_done:
                        is_packet_satisfied = False
                        break
                if not is_packet_satisfied:
                    if patient_name not in not_scheduled_packets:
                        not_scheduled_packets[patient_name] = []
                    not_scheduled_packets[patient_name].append(packet_name)
            if patient_name in not_scheduled_packets:
                not_scheduled_packets[patient_name].sort()
        
        # list all unused operators
        unused_operators = dict()
        for care_unit_name, care_unit in operators[day_name].items():
            for operator_name in care_unit.keys():
                is_operator_used = False
                for scheduled_service in daily_scheduled_services:
                    if scheduled_service["care_unit"] == care_unit_name and scheduled_service["operator"] == operator_name:
                        is_operator_used = True
                        break
                if not is_operator_used:
                    if care_unit_name not in unused_operators:
                        unused_operators[care_unit_name] = []
                    unused_operators[care_unit_name].append(operator_name)

        results[day_name] = {
            "scheduledServices": sorted(daily_scheduled_services, key=lambda r: r["patient"] + r["service"]),
            "notScheduledPackets": not_scheduled_packets,
            "unusedOperators": unused_operators
        }
    
    # removing of temporary files
    if os.path.isfile("input.lp"):
        os.remove("input.lp")
    if os.path.isfile("program.lp"):
        os.remove("program.lp")
    if os.path.isfile("output.txt"):
        os.remove("output.txt")

    return results

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Solve subproblem instances")
    parser.add_argument("-m", "--method", metavar="MET", type=str, default="asp", choices=["asp", "milp_basic", "milp_optimized", "milp_epsilon"], help="solution method used (asp|milp_basic|milp_optimized|milp_epsilon)")
    parser.add_argument("-i", "--input", metavar="IN", type=str, default="instances", help="input folder with the instances")
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
        with open("services.json", "r") as f:
            services = json.load(f)
        with open("packets.json", "r") as f:
            packets = json.load(f)
        with open("operators.json", "r") as f:
            operators = json.load(f)
        with open("priorities.json", "r") as f:
            priorities = json.load(f)
        with open("requests.json", "r") as f:
            requests = json.load(f)
        if args.verbose:
            start_time = datetime.now()
        results = solve_subproblem(services, packets, operators, priorities, requests, args.method, args.verbose)
        if args.verbose:
            end_time = datetime.now()
        with open("results.json", "w") as f:
            json.dump(results, f, indent=4)
        if args.verbose:
            delta = (end_time - start_time).total_seconds()
            print(f"finished! Time taken: {delta}s")
            total_time += delta
        os.chdir("..")

    if args.verbose:
        print(f"Solved subproblem for {instance_number} instance(s). Total time taken: {total_time}s, average: {total_time / instance_number}s")