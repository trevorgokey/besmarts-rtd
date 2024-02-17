"""
besmarts.core.optimization

Optimization of SMARTS hierarchies. 
"""

from typing import List, Callable

from besmarts.core import configs
from besmarts.core import hierarchies
from besmarts.core import trees
from besmarts.core import tree_iterators


class optimization_step:
    def __init__(self):
        self.index = 0
        self.cluster: trees.tree_node = None
        self.pcp: configs.smarts_perception_config = None
        self.operation = None
        self.overlap = 0
        self.maxmoves = 0
        self.direct_enable = True
        self.direct_limit = 10
        self.iterative_enable = True

    def copy(self):
        return optimization_step_copy(self)


def optimization_step_copy(step) -> optimization_step:
    s = optimization_step()
    s.index = step.index
    s.cluster = step.cluster
    s.pcp = step.pcp
    s.operation = step.operation
    s.overlap = step.overlap
    s.maxmoves = step.maxmoves
    s.direct_enable = step.direct_enable
    s.direct_limit = step.direct_limit
    s.iterative_enable = step.iterative_enable
    return s


class optimization_iteration:
    def __init__(self, steps):
        self.cursor = 0
        self.steps: List[optimization_step] = steps
        self.repeat = False

    def is_done(self) -> bool:
        return optimization_iteration_is_done(self)

    def next(self) -> optimization_step:
        return optimization_iteration_next(self)

    def repeat_step(self):
        return optimization_iteration_repeat_step(self)


class optimization_strategy:

    """
    Determines how to step the optimization forward, choosing which
    hyperparameters to try next. The steps are divided into macro and micro
    iterations, where the (best) nodes are created given the candidates
    produced by a single macro step consisting of one more micro steps.
    """

    MERGE = -1
    SPLIT = 1

    def __init__(self, bounds: configs.smarts_perception_config, overlaps=None):
        self.bounds: configs.smarts_perception_config = bounds

        if overlaps is None:
            self.overlaps = [0]

        # For each objective defined, pass on this many to the next objective.
        # This is a sequential filter according to each objective. A value of 0
        # means keep everything. Note that each acceptance will cause the objective
        # to be reevaluated.
        self.objective_accept_total = [0]

        # Only consider the top N clusters of each objective state
        self.objective_accept_clusters = [0]

        # Update objective on each evaluation. Some objectives change if new
        # clusters are added. This option determines whether accepting causes a refresh
        self.objective_update_on_each_accept = True

        self.cursor = -1
        self.maxedits_limit = 0
        self.repeat = False

        self.direct_enable = False
        self.direct_limit = 10

        self.iterative_enable = True

        self.enable_merge = True
        self.enable_split = True

        self.steps: List[optimization_iteration] = []
        self.tree_iterator: Callable = tree_iterators.tree_iter_dive

        self.step_tracker = {}

        # Number of operations to accept per macro step
        # Relabeling is done here
        # self.accept_max = 1 will give best performance, but will cost the most
        # self.accept_max = 0 is no max
        self.macro_accept_max_total: int = 1

        # Number of operations to accept per micro step
        # We do not relabel here but instead just keep this many
        # self.accept_max = 1 will give best performance, but will cost the most
        # self.accept_max = 0 is no max
        self.micro_accept_max_total: int = 1

        # Number of operations to accept per step per cluster
        # self.accept_max = 1 will give best performance, but will cost the most
        # self.accept_max = 0 is no max
        self.macro_accept_max_per_cluster: int = 1

        # Number of operations to accept per step per cluster
        # self.accept_max = 1 will give best performance, but will cost the most
        # self.accept_max = 0 is no max
        self.micro_accept_max_per_cluster: int = 1

        # This removes candidates which have an estimated objective diff above
        # this value
        # None disables
        # 0.0 will prune anything that is deemed useless
        self.filter_above: float = 0.0

        self.keep_below: float = 0.0

    def macro_iteration(
        self, clusters: List[trees.tree_node]
    ) -> optimization_iteration:
        """
        Return a list of iterations that form a macro iteration, where
        we may want to analyze a group of candidates before proceeding
        to the next level of searching

        Parameters
        ----------
        clusters: List[trees.tree_node]
            The nodes of a trees.tree_index to consider in the step

        Returns
        -------
        optimization_step
        """
        if not self.steps:
            self.build_steps()
        return optimization_strategy_iteration_next(self, clusters)

    def is_done(self) -> bool:
        return optimization_strategy_is_done(self)

    def restart(self):
        return optimization_strategy_restart(self)

    def repeat_step(self):
        """
        Repeat the last macro iteration by returning the same
        `optimization_iteration` in the next call to `macro_iteration`
        """
        return optimization_strategy_repeat_step(self)

    def build_steps(self):
        self.steps.extend(
            optimization_strategy_build_macro_iterations(self)
        )

def optimization_strategy_restart(os: optimization_strategy):
    os.repeat = False
    os.cursor = -1
    os.steps.clear()
    os.build_steps()
    return os


def optimization_strategy_is_done(os) -> bool:
    if not os.steps:
        os.build_steps()

    return (not os.repeat) and os.cursor >= len(os.steps)


def optimization_iteration_repeat_step(oi):
    oi.repeat = True


def optimization_strategy_repeat_step(oi):
    oi.repeat = True


def optimization_iteration_is_done(oi):
    return (not oi.repeat) and oi.cursor >= len(oi.steps)


def optimization_iteration_next(oi) -> optimization_step:
    if oi.repeat and oi.cursor > 0:
        oi.cursor -= 1
        oi.repeat = False

    if oi.is_done():
        step = optimization_step()
        step.index = -1
    else:
        step = oi.steps[oi.cursor]
        oi.cursor += 1

    return step


def optimization_strategy_iteration_next(
    oi: optimization_strategy, clusters: List[trees.tree_node]
) -> optimization_iteration:
    if oi.repeat and oi.cursor > 0:
        oi.cursor -= 1
        oi.repeat = False

    macro = None

    if not oi.steps:
        oi.steps.extend(oi.build_steps())

    if oi.is_done():
        step = optimization_step()
        step.index = -1
        macro = optimization_iteration([step])

    else:
        macro = oi.steps[oi.cursor]
        micros = []
        n = 0

        for s in macro.steps:
            for p in clusters:
                s = optimization_step_copy(s)
                s.cluster = p
                # s.operation = oi.SPLIT
                s.index = n
                n += 1
                micros.append(s)

        macro = optimization_iteration(micros)
        oi.cursor += 1

    return macro


def optimization_strategy_build_macro_iterations(strat: optimization_strategy):
    macro_iters = []
    bounds = strat.bounds.splitter
    search_cursor = -1

    for overlap in strat.overlaps:
        for branch_d in range(
            bounds.branch_depth_min, bounds.branch_depth_limit + 1
        ):
            for branches in range(bounds.branch_limit, bounds.branch_limit + 1):
                bits = bounds.bit_search_min - 1
                while bits < bounds.bit_search_limit:
                    bits += 1
                    # if branch_d == 0 and branches > 0:
                    #     continue
                    # if branch_d > 0 and branches == 0:
                    #     continue
                    # if branches > bits:
                    #     continue
                    # if branches < branch_d:
                    #     continue

                    search_cursor += 1
                    if search_cursor < strat.cursor:
                        continue

                    if strat.enable_merge:
                        steps = []
                        s = optimization_step()
                        s.index = 0
                        s.cluster = None
                        s.overlap = [overlap]
                        s.direct_enable = strat.direct_enable
                        s.direct_limit = strat.direct_limit
                        s.operation = strat.MERGE
                        s.iterative_enable = strat.iterative_enable

                        splitter = configs.smarts_splitter_config(
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            True,
                            True,
                            0,
                            strat.bounds.splitter.split_general,
                            strat.bounds.splitter.split_specific,
                            strat.bounds.splitter.unique_compliments,
                            strat.bounds.splitter.unique_compliments_prefer_min,
                        )
                        extender = configs.smarts_extender_config(0, 0, True)
                        config = configs.smarts_perception_config(
                            splitter, extender
                        )
                        s.pcp = config

                        macro_iters.append(optimization_iteration([s]))
                    if strat.enable_split:
                        steps = []
                        # this will compose with the hierarchy later
                        # during the call to next

                        s = optimization_step()
                        s.index = 0
                        s.cluster = None
                        s.overlap = [overlap]

                        s.direct_enable = strat.direct_enable
                        s.direct_limit = strat.direct_limit
                        s.iterative_enable = strat.iterative_enable

                        s.operation = strat.SPLIT

                        splitter = configs.smarts_splitter_config(
                            bits,
                            bits,
                            0,
                            branches,
                            branch_d,
                            branch_d,
                            strat.bounds.splitter.unique,
                            False,
                            0,
                            strat.bounds.splitter.split_general,
                            strat.bounds.splitter.split_specific,
                            strat.bounds.splitter.unique_compliments,
                            strat.bounds.splitter.unique_compliments_prefer_min,
                        )
                        extender = configs.smarts_extender_config(
                            branches, branches, True
                        )
                        config = configs.smarts_perception_config(
                            splitter, extender
                        )
                        s.pcp = config

                        steps.append(s)
                        macro_iters.append(optimization_iteration([s]))

                        # print("MACRO SPLIT")

                # print("MACRO MERGE")

    strat.cursor = 0

    return macro_iters