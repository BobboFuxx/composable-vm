from collections import defaultdict
from copy import copy
from attr import dataclass
from cvm_runtime.execute import Exchange
import cvxpy as cp
import numpy as np
from simulation.routers.data import AllData, AssetPairsXyk, AssetTransfers, Ctx, Input, Spawn
from anytree import Node, RenderTree
@dataclass
class CvxpySolution:
    deltas: list[cp.Variable]
    """
    how much one gives to pool i
    """

    lambdas: list[cp.Variable]
    """ 
    how much one wants to get from pool i
    """

    psi: cp.Variable
    etas: cp.Variable
    problem: cp.Problem

    @property
    def eta_values(self) -> np.ndarray[float]:
        return np.array([x.value for x in self.etas])

    @property
    def delta_values(self) -> list[np.ndarray[float]]:
        return [x.value for x in self.deltas]
    
    @property
    def lambda_values(self) -> list[np.ndarray[float]]:
        return [x.value for x in self.lambdas]

    def __post_init__(self):
        assert len(self.deltas) > 0
        assert len(self.deltas) == len(self.lambdas) == len(self.eta_values)

    @property
    def count(self):
        return len(self.deltas)
                   
    def received(self, global_index) -> float:
        return self.psi.value[global_index]


@dataclass
class VenueOperation:
    venue_index: int
    in_token: any
    in_amount : int
    out_token: any
    out_amount: any

def cvxpy_to_data(input: Input, all_data : AllData, ctx: Ctx, result: CvxpySolution) -> Node:
    """_summary_
    Converts Angeris CVXPY result to executable route.
    Receives solution along with all data and context.
    Clean up near zero trades.
    Make `delta-lambda` to be just single trades over venues.
    Start building fork-join supported route tree tracking venue.
      Find starter node and recurse with minus from input matrix (loops covered).
    Visualize.
    """
    
    _etas, trades_raw = parse_trades(ctx, result)
        
    # attach tokens ids to trades
    trades = []
    
    for i, raw_trade in enumerate(trades_raw):
        if np.abs(raw_trade[0]) > 0: 
            [token_index_a, token_index_b] = all_data.venues_tokens[i]
            if raw_trade[0] < 0:                
                trades.append(VenueOperation(in_token=token_index_a, in_amount=-raw_trade[0], out_token=token_index_b, out_amount=raw_trade[1], venue_index = i))
            else:
                trades.append(VenueOperation(in_token=token_index_b, in_amount=-raw_trade[1], out_token=token_index_a, out_amount=raw_trade[0], venue_index  = i ))
        else: 
            trades.append(None)
    
    # balances
    in_tokens = defaultdict(int)
    out_tokens= defaultdict(int)
    for trade in trades:
        if trade:
            in_tokens[trade.in_token] += trade.in_amount
            out_tokens[trade.out_token] += trade.out_amount
    
    # add nodes until burn all input from balance
    # node identity is token and amount input used and depth
    # loops naturally expressed in tree and end with burn
    def next(start_coin):
        # handle big amounts first
        from_coin = sorted([trade for trade in trades if trade and trade.in_token == start_coin.name], key = lambda x : x.in_amount, reverse=True)
        for trade in from_coin:            
            in_tokens[trade.in_token]-= trade.in_amount
            if in_tokens[trade.in_token] < 0:
                continue
            out_tokens[trade.out_token]-= trade.out_amount
            next_trade = Node(name=trade.out_token, parent=start_coin, amount = trade.out_amount, venue_index = 0)
            next(next_trade)
                    
    start_coin = Node(name=input.in_token_id, amount=input.in_amount, venue_index = 0)
    next(start_coin)
    if ctx.debug:
        for pre, fill, node in RenderTree(start_coin):
            print("%s coin=%s/%s" % (pre, node.amount, node.name))
    # convert to CVM route 
    # ..in progress - set if it Transfer or Exchange
    
    return start_coin 

def parse_trades(ctx, result):
    etas = result.eta_values
    deltas = result.delta_values
    lambdas = result.lambda_values
    
    # clean up near zero trades
    for i in range(result.count):
        if etas[i] < ctx.minimal_amount:
            etas[i] = 0
            deltas[i] = np.zeros(len(deltas[i]))
            lambdas[i] = np.zeros(len(lambdas[i]))
        
        if np.max(np.abs(deltas[i])) < ctx.minimal_amount and np.max(np.abs(lambdas[i])) < ctx.minimal_amount:
            etas[i] = 0
            deltas[i] = np.zeros(len(deltas[i]))
            lambdas[i] = np.zeros(len(lambdas[i]))            
    
    
    # trading instances
    trades_raw = []        
    for i in range(result.count):
        raw_trade = lambdas[i] - deltas[i]
        if np.max(np.abs(raw_trade)) < ctx.minimal_amount:
            etas[i] = 0
            deltas[i] = np.zeros(len(deltas[i]))
            lambdas[i] = np.zeros(len(lambdas[i]))
        trades_raw.append(lambdas[i] - deltas[i])
    for i in range(result.count):
        if not etas[i] ==0:
            etas[i] == None  
    return etas,trades_raw   
        
        