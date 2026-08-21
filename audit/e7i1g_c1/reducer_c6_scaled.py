"""C6 trace validation followed by the predeclared scaled reducer."""
from reducer_c4_scaled import reduce as scaled_reduce
from reducer_c6 import validate_trace
def reduce(trace,controls):
    validate_trace(trace)
    return scaled_reduce(trace,controls)
