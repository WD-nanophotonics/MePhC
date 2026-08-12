# MePhC Affine Architecture R6 evidence

This bundle records the first quantitative periodic-supercell Maxwell spectral-response baseline for canonical SqrLatt and TriLatt geometries.

The run is repository-only and uses /home/icy/miniconda3/envs/mp/bin/python with real meep.mpb.ModeSolver. The fixed field is A*sin(2*pi*xi1)*sin(pi*xi2)^2*e_x on a 2x2 supercell, with generic q IDs q0/q1/q2 and amplitudes 0, +0.005, -0.005, +0.0025, -0.0025.

SqrLatt passes 8 -> 12 and produces five eligible response records. TriLatt is sealed as BLOCKED_NONCONVERGED because q2 fails both 8 -> 12 and 12 -> 16. No R7 work, unfolding, topology, Berry/BCD, transport, or solver tuning was performed.

Run:

    /home/icy/miniconda3/envs/mp/bin/python run_r6_response.py
    /home/icy/miniconda3/envs/mp/bin/python validate_r6.py

