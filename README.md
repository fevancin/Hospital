# Hospital Project

Generate new instances with `generate_instances.py`:
- option `-s` specify a seed (default `42`)
- option `-n` select the number of instance to generate (default `1`)
- option `-p` accepts the prefix name for each instance folder (default `instance`)
- option `-o` specify the output directory for the instances (default `instances`)
- option `-v` to see the output in verbose format

Compute the subsumptions on the days with `compute_subsumptions.py`:
- option `-m` specify the method used (`asp` or `milp`, default `asp`)
- option `-i` specify the instances input directory (default `instances`)
- option `-v` to see the output in verbose format

Solve all subproblems with `solve_subproblems.py`:
- option `-m` specify the method used (`asp`, `milp_basic`, `milp_optimized` or `milp_epsilon`, default `asp`)
- option `-i` specify the instances input directory (default `instances`)
- option `-v` to see the output in verbose format

Compute all cores with `compute_cores.py`:
- option `-i` specify the instances input directory (default `instances`)
- option `-v` to see the output in verbose format