"""
besmarts.mm.force_pairwise
"""

from besmarts.core import mm
from besmarts.core import topology
from besmarts.core import assignments
from besmarts.core import trees
from besmarts.core import codecs
from besmarts.core import hierarchies
from besmarts.core import primitives
from besmarts.core import graphs

import subprocess
import math


class chemical_model_procedure_antechamber(mm.chemical_model_procedure):
    """
    """

    def __init__(self, topology_terms):
        self.name = ""
        self.topology_terms = topology_terms

    def assign(self, cm: mm.chemical_model, pm: mm.physical_model) -> mm.physical_model:
        """
        this would set the parameter to am1bcc and the values
        go in and look for mass procedure
        """
        symbol = "qq"
        pm.values = []
        cdc = codecs.primitive_codec_formal_charge()
        for pos in pm.positions:
            
            charges = {}
            labels = {}
            # charges = {k: [] for  k in pos.selections}
            # labels = {k: "" for  k in pos.selections}
            q = int(cdc.count_charge_smiles(pos.graph.nodes))
            nconfs = min((len(x) for x in pos.selections.values()))
            for i in range(nconfs):
                with open("mdin", "w") as f:
                    f.write(f"\n&qmmm\nqm_theory='AM1', maxcyc=0, grms_tol=0.0005, scfconv=1.d-10, ndiis_attempts=700, qmcharge={q:d},\n /\n")
                    for j, (n, xyz) in enumerate(pos.selections.items(), 1): 
                        x,y,z = xyz[i]
                        elem = pos.graph.nodes[n[0]].primitives["element"].on()[0]
                        name = primitives.element_tr[str(elem)] + str(j)
                        f.write(f"{elem} {name} {x:12.9f} {y:12.9f} {z:12.9f}\n")
                    f.write("\n")

                subprocess.run([
                    "sqm", "-O",
                    "-i", "mdin",
                    "-o", "mdout"
                    ], 
                )

                subprocess.run([
                    "antechamber",
                    "-c", "bcc", 
                    "-nc", f"{q}",
                    "-pf", "y",
                    "-dr", "n",
                    "-fi", "sqmout",
                    "-i", "mdout",
                    "-fo", "mol2",
                    "-o", "out.mol2"
                    ],
                    capture_output=True
                )
                subprocess.run([
                    "antechamber",
                    "-c", "wc", 
                    "-cf", "q.dat", 
                    "-nc", f"{q}",
                    "-pf", "y",
                    "-dr", "n",
                    "-fi", "mol2",
                    "-i", "out.mol2",
                    "-fo", "mol2",
                    "-o", "out.mol2"
                    ],
                    capture_output=True
                )
                with open("q.dat") as f:
                    qdat = f.read().split()
                    conf_charges = {
                        i: float(x) for i, x in zip(pos.graph.nodes, qdat)
                    }

                for i, qi in conf_charges.items():
                    if (i,) not in charges:
                        charges[i,] = {"q": []}
                    charges[i,]["q"].append(qi)
            pm.values.append(charges)
            pm.labels.append(labels)
        return pm

class chemical_model_procedure_combine_coulomb(mm.chemical_model_procedure):
    """
    """

    def __init__(self, top_parm):
        self.name = ""
        assert "qq" in top_parm

    def assign(self, cm, pm):

        params = pm.values
        pos = pm.positions

        pairs = assignments.smiles_assignment_geometry_distances(
            pos[0],
            graphs.graph_pairs(pos[0].graph)
        ).selections


        for param in params:
            mixed = {}
            for i,j in pairs:
                if (i,) not in param or (j,) not in param:
                    continue
                if (i,j) not in mixed:
                    mixed[i,j] = {}
                ei = param[i,].get("q")
                ej = param[j,].get("q")
                mixed[i,j]["qq"] = [(e1*e2) for e1,e2 in zip(ei, ej)]

            param.update(mixed)

        return pm

class chemical_model_procedure_combine_lj_lorentz_berthelot(mm.chemical_model_procedure):
    """
    """

    def __init__(self, top_parm):
        assert "ee" in top_parm
        assert "rr" in top_parm

    def assign(self, cm, pm):
        params = pm.values
        pos = pm.positions

        pairs = assignments.smiles_assignment_geometry_distances(
            pos[0],
            graphs.graph_pairs(pos[0].graph)
        ).selections

        for param in params:
            mixed = {}
            for i,j in pairs:
                if (i,) not in param or (j,) not in param:
                    continue
                ei = param[i,].get("e")
                ej = param[j,].get("e")
                if ei is None or ej is None:
                    continue

                if (i,j) not in mixed:
                    mixed[i,j] = {}
                mixed[i,j]["ee"] = [(e1*e2)**.5 for e1,e2 in zip(ei, ej)]

                ri = param[i,].get("r")
                rj = param[j,].get("r")
                if ri is None or rj is None:
                    continue
                mixed[i,j]["rr"] = [(r1+r2)/2.0 for r1,r2 in zip(ri, rj)]

            param.update(mixed)
        return pm

# electrostatics
def energy_function_coulomb_mix(*, eps, c, s, qq, x) -> float:
    return [s[0]*eps[0]*q/xi if xi < c[0] else 0.0 for q, xi in zip(qq, x)]

def force_function_coulomb_mix(*, eps, c, s, qq, x) -> float:
    return [-s[0]*eps[0]*q/(xi*xi) if xi < c[0] else 0.0 for q, xi in zip(qq, x)]

# vdW
def energy_function_lennard_jones_combined(*, s, c, ee, rr, x) -> float:
    xx = [math.pow(rr[0]/xi, 6) if xi < c[0] else 0.0 for xi in x]
    return [4.0*s[0]*ee[0]*(xi*xi - xi) for xi in xx]

def force_function_lennard_jones_combined(*, s, c, ee, rr, x) -> float:
    xx = [math.pow(rr[0]/x, 6) if xi < c[0] else 0.0 for xi in x]
    return [-24.0*ee[0]*s[0]*(2.0*y*y - y)/x for y in xx]

def chemical_model_coulomb_smarts(perception):

    cm = mm.chemical_model("Q", "electrostatics", topology.pair)

    cm.energy_function = energy_function_coulomb_mix
    cm.force_function = force_function_coulomb_mix
    cm.internal_function = assignments.smiles_assignment_geometry_distances
    cm.system_terms = {
        "c": mm.system_term("cutoff", "c", "float", "A", [10.0], ""),
        "eps": mm.system_term("dielectric", "eps", "float", "kcal/mol*A/e/e", [332.0636], ""),
    }

    cm.topology_terms = {
        "qq": mm.topology_term("qq", "partial_charge", "float", "e*e", {}, "", {}),
        "q": mm.topology_term("q", "partial_charge", "float", "e", {}, "", {}),
    }
    cm.topology_terms["s"] = mm.topology_term("s", "scale", "float", "", {}, "", {})


    return cm

def chemical_model_lennard_jones_smarts(perception) -> mm.chemical_model:

    cm = mm.chemical_model("N", "vdw", topology.pair)

    cm.energy_function = energy_function_lennard_jones_combined
    cm.force_function = force_function_lennard_jones_combined
    cm.internal_function = assignments.smiles_assignment_geometry_distances

    cm.topology_terms = {
        "e": mm.topology_term("e", "depth", "float", "kcal/mol", {}, "", {}),
        "r": mm.topology_term("r", "sigma", "float", "A", {}, "", {}),
        "ee": mm.topology_term("ee", "depth_combine", "float", "kcal/mol", {}, "", {}),
        "rr": mm.topology_term("rr", "sigma_combine", "float", "A", {}, "", {}),
        "s": mm.topology_term("s", "scale", "float", "", {}, "", {})
    }

    cm.system_terms = {
        "c": mm.system_term("cutoff", "c", "float", "A", [9.0], ""),
    }



    return cm
