#
# Copyright (c) 2006-2010, Prometheus Research, LLC
# Authors: Clark C. Evans <cce@clarkevans.com>,
#          Kirill Simonov <xi@resolvent.net>
#


"""
:mod:`htsql.tr.fn.encode`
=========================
"""


from ...adapter import Adapter, adapts
from ...domain import UntypedDomain
from ..encode import EncodeBySignature
from ..error import EncodeError
from ..coerce import coerce
from ..binding import LiteralBinding, CastBinding
from ..code import (NegationCode, LiteralCode, ScalarUnit, CorrelatedUnit,
                    AggregateUnit, FilteredSpace, FunctionCode)
from .signature import (NullIfSig, IfNullSig, QuantifySig, WrapExistsSig,
                        AggregateSig, CountSig,TakeCountSig,
                        MinSig, TakeMinSig, MaxSig, TakeMaxSig,
                        SumSig, TakeSumSig, AvgSig, TakeAvgSig)


class EncodeQuantify(EncodeBySignature):

    adapts(QuantifySig)

    def __call__(self):
        op = self.state.encode(self.binding.op)
        if self.signature.polarity == -1:
            op = NegationCode(op, self.binding)
        space = self.state.relate(self.binding.base)
        plural_units = [unit for unit in op.units
                             if not space.spans(unit.space)]
        if not plural_units:
            raise EncodeError("a plural operand is required", op.mark)
        plural_spaces = []
        for unit in plural_units:
            if any(plural_space.dominates(unit.space)
                   for plural_space in plural_spaces):
                continue
            plural_spaces = [plural_space
                             for plural_space in plural_spaces
                             if not unit.space.dominates(plural_space)]
            plural_spaces.append(unit.space)
        if len(plural_spaces) > 1:
            raise EncodeError("invalid plural operand", op.mark)
        plural_space = plural_spaces[0]
        if not plural_space.spans(space):
            raise EncodeError("invalid plural operand", op.mark)
        plural_space = FilteredSpace(plural_space, op, self.binding)
        op = LiteralCode(True, op.domain, self.binding)
        aggregate = CorrelatedUnit(op, plural_space, space,
                                   self.binding)
        wrapper = FunctionCode(WrapExistsSig(), op.domain, self.binding,
                               op=aggregate)
        if self.signature.polarity == -1:
            wrapper = NegationCode(wrapper, self.binding)
        wrapper = ScalarUnit(wrapper, space, self.binding)
        return wrapper


class EncodeAggregate(EncodeBySignature):

    adapts(AggregateSig)

    def take(self, op):
        return op

    def wrap(self, op):
        return op

    def __call__(self):
        op = self.take(self.state.encode(self.binding.op))
        space = self.state.relate(self.binding.base)
        plural_units = [unit for unit in op.units
                             if not space.spans(unit.space)]
        if not plural_units:
            raise EncodeError("a plural operand is required", op.mark)
        plural_spaces = []
        for unit in plural_units:
            if any(plural_space.dominates(unit.space)
                   for plural_space in plural_spaces):
                continue
            plural_spaces = [plural_space
                             for plural_space in plural_spaces
                             if not unit.space.dominates(plural_space)]
            plural_spaces.append(unit.space)
        if len(plural_spaces) > 1:
            raise EncodeError("invalid plural operand", op.mark)
        plural_space = plural_spaces[0]
        if not plural_space.spans(space):
            raise EncodeError("invalid plural operand", op.mark)
        aggregate = AggregateUnit(op, plural_space, space, self.binding)
        wrapper = self.wrap(aggregate)
        wrapper = ScalarUnit(wrapper, space, self.binding)
        return wrapper


class EncodeCount(EncodeAggregate):

    adapts(CountSig)

    def take(self, op):
        false = LiteralCode(False, op.domain, op.binding)
        op = FunctionCode(NullIfSig(), op.domain, op.binding,
                          lop=op, rops=[false])
        return FunctionCode(TakeCountSig(), self.binding.domain, self.binding,
                            op=op)

    def wrap(self, op):
        zero = LiteralBinding('0', UntypedDomain(), op.syntax)
        zero = CastBinding(zero, op.domain, op.syntax)
        zero = self.state.encode(zero)
        return FunctionCode(IfNullSig(), op.domain, op.binding,
                            lop=op, rops=[zero])


class EncodeMin(EncodeAggregate):

    adapts(MinSig)

    def take(self, op):
        return FunctionCode(TakeMinSig(), self.binding.domain, self.binding,
                            op=op)


class EncodeMax(EncodeAggregate):

    adapts(MaxSig)

    def take(self, op):
        return FunctionCode(TakeMaxSig(), self.binding.domain, self.binding,
                            op=op)


class EncodeSum(EncodeAggregate):

    adapts(SumSig)

    def take(self, op):
        return FunctionCode(TakeSumSig(), self.binding.domain, self.binding,
                            op=op)

    def wrap(self, op):
        zero = LiteralBinding('0', UntypedDomain(), op.syntax)
        zero = CastBinding(zero, op.domain, op.syntax)
        zero = self.state.encode(zero)
        return FunctionCode(IfNullSig(), op.domain, op.binding,
                            lop=op, rops=[zero])


class EncodeAvg(EncodeAggregate):

    adapts(AvgSig)

    def take(self, op):
        return FunctionCode(TakeAvgSig(), self.binding.domain, self.binding,
                            op=op)

