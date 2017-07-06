
from __future__ import print_function

import os
import sys
import tempfile

import gringo

from caspo.core import Graph, HyperGraph, LogicalNetwork, LogicalNetworkList

from .networks import *
from .utils import *
from .asputils import *
from .dataset import *
from caspots import identify
from caspots import modelchecking


def read_pkn(args):
    graph = Graph.read_sif(args.pkn)
    hypergraph = HyperGraph.from_graph(graph)
    return graph, hypergraph

def dataset_name(args):
    return os.path.basename(args.dataset).replace(".csv", "")

def read_dataset(args, graph):
    ds = Dataset(dataset_name(args), dfactor=args.factor)
    ds.load_from_midas(args.dataset, graph)
    return ds

def read_networks(args):
    networks = LogicalNetworkList.from_csv(args.networks)
    if args.range_from:
        end = len(networks)
        if args.range_length:
            end = args.range_from + args.range_length
        indexes = range(args.range_from, end)
        networks = networks[indexes]
    return networks, networks.hg

def read_domain(args, hypergraph, dataset, outf):
    if args.networks:
        networks, hypergraph = read_networks(args)
        out = domain_of_networks(networks)
        with open(outf, "w") as fd:
            fd.write(out)
        return outf, hypergraph
    else:
        return None, hypergraph

def read_restriction(args, hypergraph, outf):
    if args.partial_bn:
        asp = restrict_with_partial_bn(hypergraph, args.partial_bn)
        with open(outf, "w") as fd:
            fd.write(asp)
        return outf
    return None

def is_true_positive(args, dataset, network):
    fd, smvfile = tempfile.mkstemp(".smv")
    os.close(fd)
    exact = modelchecking.verify(dataset, network, smvfile, args.semantics)
    if args.debug:
        dbg("# %s" % smvfile)
    else:
        os.unlink(smvfile)
    return exact

def do_pkn2lp(args):
    funset(read_pkn(args)[1]).to_file(args.output)

def do_midas2lp(args):
    graph, _ = read_pkn(args)
    dataset = read_dataset(args, graph)
    funset(dataset).to_file(args.output)

def do_results2lp(args):
    graph, hypergraph = read_pkn(args)
    dataset = read_dataset(args, graph)
    networks, hypergraph = read_networks(args)
    out = domain_of_networks(networks)
    print(out)

def do_mse(args):
    graph, hypergraph = read_pkn(args)
    dataset = read_dataset(args, graph)

    fd, domainlp = tempfile.mkstemp(".lp")
    os.close(fd)
    domain, hypergraph = read_domain(args, hypergraph, dataset, domainlp)

    termset = funset(hypergraph, dataset)

    fd, restrictlp = tempfile.mkstemp(".lp")
    os.close(fd)
    restrict = read_restriction(args, hypergraph, restrictlp)

    identifier = identify.ASPSolver(termset, args, domain=domain,
                                    restrict=restrict)

    first = True
    exact = False
    for sample in identifier.solution_samples():
        (mse0, mse) = sample.mse()
        if first:
            print("MSE_discrete = %s" % mse0)
            if mse0 == mse:
                print("MSE_sample >= MSE_discrete")
            else:
                print("MSE_sample >= %s" % mse)
        if args.check_exact:
            network = sample.network(hypergraph)
            trace = sample.trace(dataset)
            exact = is_true_positive(args, trace, network)
            if exact:
                break
        else:
            break
        first = False
    if args.check_exact:
        if exact:
            print("MSE_sample is exact")
        else:
            print("MSE_sample may be under-estimated (no True Positive found)")
    os.unlink(domainlp)
    os.unlink(restrictlp)


def do_identify(args):
    graph, hypergraph = read_pkn(args)
    dataset = read_dataset(args, graph)

    fd, domainlp = tempfile.mkstemp(".lp")
    os.close(fd)
    domain, hypergraph = read_domain(args, hypergraph, dataset, domainlp)

    termset = funset(hypergraph, dataset)

    fd, restrictlp = tempfile.mkstemp(".lp")
    os.close(fd)
    restrict = read_restriction(args, hypergraph, restrictlp)

    identifier = identify.ASPSolver(termset, args, domain=domain,
                                    restrict=restrict)

    networks = LogicalNetworkList.from_hypergraph(hypergraph)

    c = {
        "found": 0,
        "tp": 0,
    }
    def show_stats(output=sys.stderr):
        if args.true_positives:
            output.write("%d solution(s) / %d true positives\r" % (c["found"], c["tp"]))
        else:
            output.write("%d solution(s)\r" % c["found"])
        output.flush()


    def update(network, exact, new=True):
        if new:
            c["found"] += 1
        if args.true_positives and exact:
            c["tp"] += 1
        show_stats()
        if not args.true_positives or exact:
            networks.append(network)

    def on_model(model):
        tuples = (f.args() for f in model.atoms() if f.name() == "dnf")
        network = LogicalNetwork.from_hypertuples(hypergraph, tuples)
        tp = args.true_positives and is_true_positive(args, dataset, network)
        update(network, tp)

    if args.true_positives:
        known_networks = set()
        def on_model_with_errors(sample):
            network = sample.network(hypergraph)
            trace = sample.trace(dataset)
            if args.enum_traces:
                h = hash(tuple(network.to_array(hypergraph.mappings)))
                new = h not in known_networks
                if new:
                    known_networks.add(h)
            else:
                new = True
            update(network, is_true_positive(args, trace, network), new)
    else:
        on_model_with_errors = None

    try:
        identifier.solutions(on_model, on_model_with_errors,
                limit=args.limit, force_weight=args.force_weight)
    finally:
        print("%d solution(s) for the over-approximation" % c["found"])
        if args.true_positives and c["found"]:
            print("%d/%d true positives [rate: %0.2f%%]" \
                % (c["tp"], c["found"], (100.*c["tp"])/c["found"]))
        if networks:
            networks.to_csv(args.output)
        os.unlink(domainlp)
        os.unlink(restrictlp)



def do_validate(args):
    graph, hypergraph = read_pkn(args)
    dataset = read_dataset(args, graph)
    networks, hypergraph = read_networks(args)

    tp = 0
    c = 0
    nb = len(networks)
    tp_indexes = []
    try:
        for network in networks:
            c += 1
            sys.stderr.write("%d/%d... " % (c,nb))
            sys.stderr.flush()
            if is_true_positive(args, dataset, network):
                tp_indexes.append(c-1)
                tp += 1
            sys.stderr.write("%d/%d true positives\r" % (tp,c))
        res = "%d/%d true positives [rate: %0.2f%%]" % (tp, nb, (100.*tp)/nb)
        print(res)
        if args.tee:
            with open(args.tee, "w") as f:
                f.write("%s\n" % res)
    finally:
        if args.output and tp_indexes:
            networks[tp_indexes].to_csv(args.output)


from argparse import ArgumentParser

def run():

    parser = ArgumentParser(prog=sys.argv[0])
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--debug-dir", type=str, default=tempfile.gettempdir())
    subparsers = parser.add_subparsers(help="commands help")

    identify_parser = ArgumentParser(add_help=False)
    identify_parser.add_argument("--family", choices=["all", "subset", "mincard"],
                                    default="subset",
                                    help="result family (default: subset)")
    identify_parser.add_argument("--mincard-tolerance", type=int, default=0,
                                    help="consider (subset minimal) solutions with cardinality at most tolerance + the minimum cardinality")
    identify_parser.add_argument("--weight-tolerance", type=int, default=0,
                                    help="consider (subset minimal) solutions with weight at most tolerance + the minimum weight")
    identify_parser.add_argument("--enum-traces", action="store_true",
                                    default=False,
                                    help="enumerate over traces")
    identify_parser.add_argument("--fully-controllable", action="store_true",
                                    help="only consider BNs where all nodes have a stimulus in their ancestors (default)")
    identify_parser.add_argument("--no-fully-controllable", action="store_false", dest="fully_controllable",
                                    help="do not only consider BNs where all nodes have a stimulus in their ancestors")
    identify_parser.set_defaults(fully_controllable=True)
    identify_parser.add_argument("--force-weight", type=int, default=None,
                                    help="Force the maximum weight of a solution")
    identify_parser.add_argument("--force-size", type=int, default=None,
                                    help="Force the maximum size of a solution")
    modelchecking_p = ArgumentParser(add_help=False)
    modelchecking_p.add_argument("--semantics",
        choices=modelchecking.MODES, default=modelchecking.U_GENERAL,
        help="Updating mode of the Boolean network (default: %s)" \
            % modelchecking.U_GENERAL)

    pkn_parser = ArgumentParser(add_help=False)
    pkn_parser.add_argument("pkn", help="Prior knowledge network (sif format)")
    dataset_parser = ArgumentParser(add_help=False)
    dataset_parser.add_argument("dataset", help="Dataset (midas csv format)")
    dataset_parser.add_argument("--factor", type=int, default=100,
                                    help="discretization factor (default: 100)")

    networks_parser = ArgumentParser(add_help=False)
    networks_parser.add_argument("--range-from", type=int, default=0,
        help="Validate only networks from given row (starting at 0)")
    networks_parser.add_argument("--range-length", type=int, default=0,
        help="Number of networks to validate (0 means all)")

    domain_parser = ArgumentParser(add_help=False,
        parents=[networks_parser])
    domain_parser.add_argument("--networks", help="Networks to as domain (.csv)")
    domain_parser.add_argument("--partial-bn", help="Partial specification of the Boolean network (.bn)")

    parser_pkn2lp = subparsers.add_parser("pkn2lp",
        help="Export PKN (sif format) to ASP (lp format)",
        parents=[pkn_parser])
    parser_pkn2lp.add_argument("output", help="Output file (.lp format)")
    parser_pkn2lp.set_defaults(func=do_pkn2lp)

    parser_midas2lp = subparsers.add_parser("midas2lp",
        help="Export dataset (midas csv format) to ASP (lp format)",
        parents=[pkn_parser, dataset_parser])
    parser_midas2lp.add_argument("output", help="Output file (.lp format)")
    parser_midas2lp.set_defaults(func=do_midas2lp)

    parser_results2lp = subparsers.add_parser("results2lp",
        help="Export results to ASP (lp format)",
        parents=[pkn_parser, dataset_parser, networks_parser])
    parser_results2lp.add_argument("networks", help="Networks file (.csv format)")
    parser_results2lp.set_defaults(func=do_results2lp)

    parser_mse = subparsers.add_parser("mse",
        help="Compute the best MSE",
        parents=[pkn_parser, dataset_parser, identify_parser,
                    modelchecking_p, domain_parser])
    parser_mse.add_argument("--check-exact", action="store_true", default=False,
                            help="look for a true positive with the computed MSE")
    parser_mse.set_defaults(func=do_mse)

    parser_identify = subparsers.add_parser("identify",
        help="Identify all the best Boolean networks",
        parents=[pkn_parser, dataset_parser, identify_parser,
                    modelchecking_p, domain_parser])
    parser_identify.add_argument("--true-positives", default=False, action="store_true",
        help="filter solutions to keep only true positives (exact identification)")
    parser_identify.add_argument("--limit", default=0, type=int,
        help="Limit the number of solutions")
    parser_identify.add_argument("output", help="output file (csv format)")
    parser_identify.set_defaults(func=do_identify)

    parser_validate = subparsers.add_parser("validate",
        help="Compute the true positive rate of *exactly* identified networks",
        parents=[pkn_parser, dataset_parser,
                    modelchecking_p])
    parser_validate.add_argument("--range-from", type=int, default=0,
        help="Validate only networks from given row (starting at 0)")
    parser_validate.add_argument("--range-length", type=int, default=0,
        help="Number of networks to validate (0 means all)")
    parser_validate.add_argument("--output", 
        help="output true positive network to file (csv format)")
    parser_validate.add_argument("--tee", type=str, default=None,
        help="Output result to given file (in addition to stdout).")
    parser_validate.add_argument("networks", help="network set (csv format)")
    parser_validate.set_defaults(func=do_validate)

    args = parser.parse_args()
    print("#### OPTIONS ######")
    for k,v in args._get_kwargs():
        if k in ["func"]:
            continue
        print("# %s = %s" % (k,v))
    print("###################")
    args.func(args)

