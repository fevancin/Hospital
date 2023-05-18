import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

from pyomo.environ import ConcreteModel, SolverFactory, maximize, TerminationCondition
from pyomo.environ import Set, Var, Objective, Constraint
from pyomo.environ import Boolean

asp_program = """
% choose variables for each Less operator contained in More
{ choose(Less, More) } :-
    less(Less, LessStart, LessDuration),
    more(More, MoreStart, MoreDuration),
    LessStart >= MoreStart,
    LessStart + LessDuration <= MoreStart + MoreDuration.

% every Less operator must choose exactly one More
:- #count { More : choose(Less, More) } != 1, less(Less, _, _).

% it's impossible that two Less choose the same More if they overlap
:- choose(Less1, More), choose(Less2, More), Less1 != Less2,
    less(Less1, LessStart1, LessDuration1),
    less(Less2, LessStart2, _),
    LessStart1 <= LessStart2,
    LessStart1 + LessDuration1 > LessStart2.

#show choose/2.
"""

# get all the care unit names in the input
def get_care_unit_names(operators):
    care_unit_names = set()
    for day in operators.values():
        for care_unit_name in day.keys():
            care_unit_names.add(care_unit_name)
    return sorted(care_unit_names)

# true if it exists a match
def is_asp_program_satisfiable(more_operators, less_operators):
    more_program = ""
    for more_operator_name, more_operator in more_operators.items(): # write the input program
        more_program += f"more({more_operator_name}, {more_operator['start']}, {more_operator['duration']}).\n"
    less_program = ""
    for less_operator_name, less_operator in less_operators.items(): # write the input program
        less_program += f"less({less_operator_name}, {less_operator['start']}, {less_operator['duration']}).\n"
    with open("input.lp", "w") as f:
        f.write(more_program + less_program)
    with open("program.lp", "w") as f:
        f.write(asp_program)
    with open("output.txt", "w") as f:
        subprocess.run(["clingo", "input.lp", "program.lp"], stdout=f, stderr=subprocess.DEVNULL)
    with open("output.txt", "r") as f:
        if "UNSATISFIABLE" not in f.read():
            return True
    return False

def is_milp_program_satisfiable(more_operators, less_operators):
    x_indexes = []
    for more_operator_name, more_operator in more_operators.items():
        for less_operator_name, less_operator in less_operators.items():
            if more_operator["start"] <= less_operator["start"] and more_operator["start"] + more_operator["duration"] >= less_operator["start"] + less_operator["duration"]:
                x_indexes.append((less_operator_name, more_operator_name))
    less_indexes = []
    for less_operator_name in less_operators.keys():
        less_indexes.append(less_operator_name)
    overlap_indexes = []
    for index1 in range(len(x_indexes) - 1):
        for index2 in range(index1 + 1, len(x_indexes)):
            if x_indexes[index1][1] != x_indexes[index2][1] or x_indexes[index1][0] == x_indexes[index2][0]:
                continue
            if ((less_operators[x_indexes[index1][0]]["start"] <= less_operators[x_indexes[index2][0]]["start"] and
                less_operators[x_indexes[index1][0]]["start"] + less_operators[x_indexes[index1][0]]["duration"] > less_operators[x_indexes[index2][0]]["start"]) or
                (less_operators[x_indexes[index2][0]]["start"] <= less_operators[x_indexes[index1][0]]["start"] and
                 less_operators[x_indexes[index2][0]]["start"] + less_operators[x_indexes[index2][0]]["duration"] > less_operators[x_indexes[index1][0]]["start"])):
                overlap_indexes.append((x_indexes[index1][0], x_indexes[index2][0], x_indexes[index1][1]))
    model = ConcreteModel()
    model.x_indexes = Set(initialize=x_indexes)
    model.choose_one_indexes = Set(initialize=less_indexes)
    model.not_overlap_indexes = Set(initialize=overlap_indexes)
    model.x = Var(model.x_indexes, domain=Boolean)
    def f(model):
        return sum(model.x[l, m] for l, m in model.x_indexes)
    model.objective = Objective(rule=f, sense=maximize)
    def f1(model, less_operator_index):
        return sum(model.x[l, m] for l, m in model.x_indexes if l == less_operator_index) == 1
    model.choose_one = Constraint(model.choose_one_indexes, rule=f1)
    def f2(model, less_operator_index1, less_operator_index2, more_operator_index):
        return model.x[less_operator_index1, more_operator_index] + model.x[less_operator_index2, more_operator_index] <= 1
    model.not_overlap = Constraint(model.not_overlap_indexes, rule=f2)
    opt = SolverFactory("gurobi")
    results = opt.solve(model)
    if results.solver.termination_condition == TerminationCondition.infeasible:
        return False
    return True

def compute_subsumptions(operators, method):
    subsumptions = dict()
    for care_unit_name in get_care_unit_names(operators): # for each care unit
        care_unit_subsumptions = dict()
        for more_day_name, more_day in operators.items(): # for each more day
            if len(more_day) == 0:
                continue
            less_day_names = set()
            more_total_duration = 0
            for more_operator in more_day[care_unit_name].values(): # write the input program
                more_total_duration += more_operator["duration"] # sum the operators" duration
            for less_day_name, less_day in operators.items(): # for each less day
                if more_day_name == less_day_name: # symmetric check
                    continue
                if len(less_day) == 0:
                    continue
                if less_day_name in less_day_names: # if already in the less list
                    continue
                less_total_duration = 0
                all_less_operators_are_satisfiable = True
                for less_operator in less_day[care_unit_name].values(): # write che input program
                    less_total_duration += less_operator["duration"] # sum the operators" duration
                    is_operator_satisfiable = False
                    for more_operator in more_day[care_unit_name].values(): # search at least one more operator that contains the less one
                        if more_operator["start"] <= less_operator["start"] and more_operator["start"] + more_operator["duration"] >= less_operator["start"] + less_operator["duration"]:
                            is_operator_satisfiable = True
                            break
                    if not is_operator_satisfiable:
                        all_less_operators_are_satisfiable = False
                        break
                if less_total_duration > more_total_duration: # check for impossibility regarding the total durations
                    continue
                if not all_less_operators_are_satisfiable: # check for impossibility regarding operators satisfiability
                    continue
                if len(less_day[care_unit_name]) == 1:
                    less_day_names.add(less_day_name) # add the subsumption if a match exists
                    if less_day_name in care_unit_subsumptions: # relation transitivity check
                        less_day_names.update(care_unit_subsumptions[less_day_name])
                less_operator_list = list(less_day[care_unit_name].values())
                there_is_overlap = False
                for index1 in range(len(less_operator_list) - 1):
                    for index2 in range(index1 + 1, len(less_operator_list)):
                        if less_operator_list[index1]["start"] <= less_operator_list[index2]["start"] and less_operator_list[index1]["start"] + less_operator_list[index1]["duration"] > less_operator_list[index2]["start"] + less_operator_list[index2]["duration"]:
                            there_is_overlap = True
                            break
                        if less_operator_list[index2]["start"] <= less_operator_list[index1]["start"] and less_operator_list[index2]["start"] + less_operator_list[index2]["duration"] > less_operator_list[index1]["start"] + less_operator_list[index1]["duration"]:
                            there_is_overlap = True
                            break
                    if there_is_overlap:
                        break
                if method == "asp":
                    if not there_is_overlap or is_asp_program_satisfiable(more_day[care_unit_name], less_day[care_unit_name]):
                        less_day_names.add(less_day_name) # add the subsumption if a match exists
                        if less_day_name in care_unit_subsumptions: # relation transitivity check
                            less_day_names.update(care_unit_subsumptions[less_day_name])
                elif method == "milp":
                    if not there_is_overlap or is_milp_program_satisfiable(more_day[care_unit_name], less_day[care_unit_name]):
                        less_day_names.add(less_day_name) # add the subsumption if a match exists
                        if less_day_name in care_unit_subsumptions: # relation transitivity check
                            less_day_names.update(care_unit_subsumptions[less_day_name])
            if len(less_day_names) > 0:
                care_unit_subsumptions[more_day_name] = sorted(less_day_names)
        subsumptions[care_unit_name] = care_unit_subsumptions
    # removing of temporary working files
    if os.path.isfile("input.lp"):
        os.remove("input.lp")
    if os.path.isfile("program.lp"):
        os.remove("program.lp")
    if os.path.isfile("output.txt"):
        os.remove("output.txt")
    return subsumptions

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Compute thesubsumption relation for each instance")
    parser.add_argument("-m", "--method", metavar="MET", type=str, default="asp", choices=["asp", "milp"], help="solution method used (asp|milp)")
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

    for folder_name in os.listdir("."):
        os.chdir(folder_name)
        if args.verbose:
            print(f"Read instance '{folder_name}' ... ", end=" ")
        with open("operators.json", "r") as f:
            operators = json.load(f)
        if args.verbose:
            start_time = datetime.now()
        subsumptions = compute_subsumptions(operators, args.method)
        if args.verbose:
            end_time = datetime.now()
        with open("subsumptions.json", "w") as f:
            json.dump(subsumptions, f, indent=4)
        if args.verbose:
            delta = (end_time - start_time).total_seconds()
            print(f"finished! Time taken: {delta}s")
            total_time += delta
        os.chdir("..")

    if args.verbose:
        print(f"Computed subsumptions for {instance_number} instance(s). Total time taken: {total_time}s, average: {total_time / instance_number}s")