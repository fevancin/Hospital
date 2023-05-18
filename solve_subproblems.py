import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

from pyomo.environ import ConcreteModel, SolverFactory, maximize, TerminationCondition
from pyomo.environ import Set, Var, Objective, Constraint
from pyomo.environ import Boolean

def solve_subproblem(services, packets, operators, priorities, requests, method):
    return {}

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Solve subproblem instances")
    parser.add_argument("-m", "--method", metavar="MET", type=str, default="asp", choices=["asp", "milp_basic", "milp_optimized", "milp_epsilon"], help="solution method used (asp|milp_basic|milp_optimized|milp_epsilon)")
    parser.add_argument("-i", "--input", metavar="IN", type=str, default="instances", help="input folder with the instances")
    parser.add_argument("-v", "--verbose", action="store_true", help="show what is done")
    args = parser.parse_args(sys.argv[1:])

    os.chdir(os.path.dirname(sys.argv[0]))

    if not os.path.isdir(args.input):
        raise FileNotFoundError(f"Input folder '{args.input}' not found")
    os.chdir(args.input)

    instance_number = len(os.listdir("."))
    if instance_number == 0:
        print("No instance folder found. No action taken.")
        exit(0)

    if args.verbose:
        total_time = 0

    for folder_name in os.listdir("."):
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
        results = solve_subproblem(services, packets, operators, priorities, requests, args.method)
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