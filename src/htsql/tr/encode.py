#
# Copyright (c) 2006-2011, Prometheus Research, LLC
# See `LICENSE` for license information, `AUTHORS` for the list of authors.
#


"""
:mod:`htsql.tr.encode`
======================

This module implements the encoding process.
"""


from ..adapter import Adapter, adapts, adapts_many
from ..domain import (Domain, UntypedDomain, TupleDomain, BooleanDomain,
                      NumberDomain, IntegerDomain, DecimalDomain, FloatDomain,
                      StringDomain, EnumDomain, DateDomain, TimeDomain,
                      DateTimeDomain, OpaqueDomain)
from .error import EncodeError
from .coerce import coerce
from .binding import (Binding, QueryBinding, SegmentBinding, WrappingBinding,
                      HomeBinding, RootBinding, FreeTableBinding,
                      AttachedTableBinding, ColumnBinding,
                      QuotientBinding, KernelBinding, ComplementBinding,
                      CoverBinding, ForkBinding, LinkBinding, SieveBinding,
                      SortBinding, CastBinding, RescopingBinding,
                      LiteralBinding, FormulaBinding)
from .lookup import direct
from .flow import (RootFlow, ScalarFlow, DirectTableFlow, FiberTableFlow,
                   QuotientFlow, ComplementFlow, MonikerFlow, ForkedFlow,
                   LinkedFlow, FilteredFlow, OrderedFlow,
                   QueryExpr, SegmentExpr, LiteralCode, FormulaCode,
                   CastCode, ColumnUnit, ScalarUnit, KernelUnit)
from .signature import Signature, IsNullSig, NullIfSig
import decimal


class EncodingState(object):
    """
    Encapsulates the (mutable) state of the encoding process.

    Currently encoding is a stateless process, but we will likely add
    extra state in the future.  The state is also used to store the
    cache of binding to flow and binding to code translations.
    """

    # Indicates whether results of `encode` or `relate` are cached.
    # Caching means that two calls of `encode` (or `relate`) on the
    # same `Binding` instance produce the same object.
    #
    # By default, caching is turned on; however the translator must
    # never rely on that.  That is, the result generated by the
    # translator must not depend on whether caching is enabled or
    # disabled.  This parameter gives us an easy way to check this
    # assumption.  Different results usually mean a bug in comparison
    # by value for code objects.
    with_cache = True

    def __init__(self):
        # A mapping of cached results of `encode()`.
        self.binding_to_code = {}
        # A mapping of cached results of `relate()`.
        self.binding_to_flow = {}

    def flush(self):
        """
        Clears the encoding state.
        """
        self.binding_to_code.clear()
        self.binding_to_state.clear()

    def encode(self, binding):
        """
        Encodes the given binding node to a code expression node.

        Returns a :class:`htsql.tr.flow.Code` node (in some cases,
        a :class:`htsql.tr.flow.Expression` node).

        `binding` (:class:`htsql.tr.binding.Binding`)
            The binding node to encode.
        """
        # When caching is enabled, we check if `binding` was
        # already encoded.  If not, we encode it and save the
        # result.
        if self.with_cache:
            if binding not in self.binding_to_code:
                code = encode(binding, self)
                self.binding_to_code[binding] = code
            return self.binding_to_code[binding]
        # Caching is disabled; return a new instance every time.
        return encode(binding, self)

    def relate(self, binding):
        """
        Encodes the given binding node to a flow expression node.

        Returns a :class:`htsql.tr.flow.Flow` node.

        `binding` (:class:`htsql.tr.binding.Binding`)
            The binding node to encode.
        """
        # When caching is enabled, we check if `binding` was
        # already encoded.  If not, we encode it and save the
        # result.
        if self.with_cache:
            if binding not in self.binding_to_flow:
                flow = relate(binding, self)
                self.binding_to_flow[binding] = flow
            return self.binding_to_flow[binding]
        # Caching is disabled; return a new instance every time.
        return relate(binding, self)


class EncodeBase(Adapter):
    """
    Applies an encoding adapter to a binding node.

    This is a base class for the two encoding adapters: :class:`Encode`
    and :class:`Relate`; it encapsulates methods and attributes shared
    between these adapters.

    The encoding process translates binding nodes to data flows or
    expressions over data flows.

    `binding` (:class:`htsql.tr.binding.Binding`)
        The binding node to encode.

    `state` (:class:`EncodingState`)
        The current state of the encoding process.
    """

    adapts(Binding)

    def __init__(self, binding, state):
        assert isinstance(binding, Binding)
        assert isinstance(state, EncodingState)
        self.binding = binding
        self.state = state


class Encode(EncodeBase):
    """
    Translates a binding node to a code expression node.

    This is an interface adapter; see subclasses for implementations.

    The :class:`Encode` adapter has the following signature::

        Encode: (Binding, EncodingState) -> Expression

    The adapter is polymorphic on the `Binding` argument.

    This adapter provides non-trivial implementation for binding
    nodes representing HTSQL functions and operators.
    """

    def __call__(self):
        # The default implementation generates an error.
        # FIXME: a better error message?
        raise EncodeError("expected a valid code expression",
                          self.binding.mark)


class Relate(EncodeBase):
    """
    Translates a binding node to a data flow node.

    This is an interface adapter; see subclasses for implementations.

    The :class:`Relate` adapter has the following signature::

        Relate: (Binding, EncodingState) -> Flow

    The adapter is polymorphic on the `Binding` argument.

    The adapter provides non-trivial implementations for scoping
    and chaining bindings.
    """

    def __call__(self):
        # The default implementation generates an error.
        # FIXME: a better error message?
        raise EncodeError("expected a valid flow expression",
                          self.binding.mark)


class EncodeQuery(Encode):

    adapts(QueryBinding)

    def __call__(self):
        # Encode the segment node if it is provided.
        segment = None
        if self.binding.segment is not None:
            segment = self.state.encode(self.binding.segment)
        # Construct the expression node.
        return QueryExpr(segment, self.binding)


class EncodeSegment(Encode):

    adapts(SegmentBinding)

    def __call__(self):
        # List of output columns.
        elements = []
        # Encode output columns of the segment.
        for binding in self.binding.elements:
            # Encode the node.
            element = self.state.encode(binding)
            elements.append(element)
        # Determine the output flow.  If a flow binding is provided,
        # use it to generate a flow node.
        if self.binding.seed is not None:
            flow = self.state.relate(self.binding.seed)
        # Otherwise, infer the output flow from output columns.
        else:
            # List of all unit expressions.
            units = []
            for element in elements:
                units.extend(element.units)
            # No units means a root scalar flow.
            if not units:
                flow = RootFlow(None, self.binding)
            # Otherwise, find a dominating unit flow.
            else:
                # List of dominating flows.
                flows = []
                for unit in units:
                    if any(flow.dominates(unit.flow) for flow in flows):
                        continue
                    flows = [flow for flow in flows
                                  if unit.flow.dominates(flow)]
                    flows.append(unit.flow)
                # More than one dominating flow means the output flow
                # cannot be inferred from the columns unambiguously.
                if len(flows) > 1:
                    raise EncodeError("invalid segment operand",
                                      self.binding.mark)
                # Otherwise, `flows` contains a single maximal flow node.
                else:
                    [flow] = flows
        return SegmentExpr(flow, elements, self.binding)


class RelateRoot(Relate):

    adapts(RootBinding)

    def __call__(self):
        # The root binding gives rise to a root flow.
        return RootFlow(None, self.binding)


class RelateHome(Relate):

    adapts(HomeBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # A home binding gives rise to a scalar flow.
        return ScalarFlow(base, self.binding)


class RelateFreeTable(Relate):

    adapts(FreeTableBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # Produce a link from a scalar to a table class.
        return DirectTableFlow(base, self.binding.table, self.binding)


class RelateAttachedTable(Relate):

    adapts(AttachedTableBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # Produce a link between table classes.
        return FiberTableFlow(base, self.binding.join, self.binding)


class RelateSieve(Relate):

    adapts(SieveBinding)

    def __call__(self):
        # Generate the parent flow.
        flow = self.state.relate(self.binding.base)
        # Encode the predicate expression.
        filter = self.state.encode(self.binding.filter)
        # Produce a filtering flow operation.
        return FilteredFlow(flow, filter, self.binding)


class RelateSort(Relate):

    adapts(SortBinding)

    def __call__(self):
        # Generate the parent flow.
        flow = self.state.relate(self.binding.base)
        # List of pairs `(code, direction)` containing the expressions
        # to sort by and respective direction indicators.
        order = []
        # Iterate over ordering binding nodes.
        for binding in self.binding.order:
            # Encode the binding node.
            code = self.state.encode(binding)
            # Extract the direction modifier; assume `+` if none.
            direction = direct(binding)
            if direction is None:
                direction = +1
            order.append((code, direction))
        # The slice indicators.
        limit = self.binding.limit
        offset = self.binding.offset
        # Produce an ordering flow operation.
        return OrderedFlow(flow, order, limit, offset, self.binding)


class RelateQuotient(Relate):

    adapts(QuotientBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # Generate the seed flow of the quotient.
        seed = self.state.relate(self.binding.seed)
        # Verify that the seed is a plural descendant of the parent flow.
        if base.spans(seed):
            raise EncodeError("a plural operand is required", seed.mark)
        if not seed.spans(base):
            raise EncodeError("invalid plural operand", seed.mark)
        # Encode the kernel expressions.
        kernels = [self.state.encode(binding)
                   for binding in self.binding.kernels]
        # Produce a quotient flow.
        return QuotientFlow(base, seed, kernels, self.binding)


class RelateComplement(Relate):

    adapts(ComplementBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # Produce a complement flow.
        return ComplementFlow(base, self.binding)


class RelateMoniker(Relate):

    adapts(CoverBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # Generate the seed flow.
        seed = self.state.relate(self.binding.seed)
        # Produce a masking flow operation.
        return MonikerFlow(base, seed, self.binding)


class RelateFork(Relate):

    adapts(ForkBinding)

    def __call__(self):
        # Generate the parent flow.
        base = self.state.relate(self.binding.base)
        # The seed coincides with the parent flow -- but could be changed
        # after the rewrite step.
        seed = base
        # Generate the fork kernel.
        kernels = [self.state.encode(binding)
                   for binding in self.binding.kernels]
        # Verify that the kernel is singular against the parent flow.
        for code in kernels:
            if not all(seed.spans(unit.flow) for unit in code.units):
                raise EncodeError("a singular operand is required", code.mark)
        return ForkedFlow(base, seed, kernels, self.binding)


class RelateLink(Relate):

    adapts(LinkBinding)

    def __call__(self):
        # Generate the parent and the seed flows.
        base = self.state.relate(self.binding.base)
        seed = self.state.relate(self.binding.seed)
        # Encode linking expressions.
        images = [(self.state.encode(lbinding), self.state.encode(rbinding))
                  for lbinding, rbinding in self.binding.images]
        # Verify that linking pairs are singular against the parent and
        # the seed flows.
        for lcode, rcode in images:
            if not all(base.spans(unit.flow) for unit in lcode.units):
                raise EncodeError("a singular operand is required", lcode.mark)
            if not all(seed.spans(unit.flow) for unit in rcode.units):
                raise EncodeError("a singular operand is required", rcode.mark)
        return LinkedFlow(base, seed, images, self.binding)


class EncodeColumn(Encode):

    adapts(ColumnBinding)

    def __call__(self):
        # Find the flow of the column.
        flow = self.state.relate(self.binding.base)
        # Generate a column unit node on the flow.
        return ColumnUnit(self.binding.column, flow, self.binding)


class RelateColumn(Relate):

    adapts(ColumnBinding)

    def __call__(self):
        # If the column binding has an associated table binding node,
        # delegate the adapter to it.
        if self.binding.link is not None:
            return self.state.relate(self.binding.link)
        # Otherwise, let the parent produce an error message.
        return super(RelateColumn, self).__call__()


class EncodeKernel(Encode):

    adapts(KernelBinding)

    def __call__(self):
        # Get the quotient flow of the kernel.
        flow = self.state.relate(self.binding.base)
        # Extract the respective kernel expression from the flow.
        code = flow.family.kernels[self.binding.index]
        # Generate a unit expression.
        return KernelUnit(code, flow, self.binding)


class EncodeLiteral(Encode):

    adapts(LiteralBinding)

    def __call__(self):
        # Switch the class from `Binding` to `Code` keeping all attributes.
        return LiteralCode(self.binding.value, self.binding.domain,
                           self.binding)


class EncodeCast(Encode):

    adapts(CastBinding)

    def __call__(self):
        # Delegate it to the `Convert` adapter.
        convert = Convert(self.binding, self.state)
        return convert()


class Convert(Adapter):
    """
    Encodes a cast binding to a code node.

    This is an auxiliary adapter used to encode
    :class:`htsql.tr.binding.CastBinding` nodes.  The adapter is polymorphic
    by the origin and the target domains.

    The purpose of the adapter is multifold.  The :class:`Convert` adapter:

    - verifies that the conversion from the source to the target
      domain is admissible;
    - eliminates redundant conversions;
    - handles conversion from the special types:
      :class:`htsql.domain.UntypedDomain` and :class:`htsql.domain.TupleDomain`;
    - when possible, expresses the cast in terms of other operations; otherwise,
      generates a new :class:`htsql.tr.flow.CastCode` node.

    `binding` (:class:`htsql.tr.binding.CastBinding`)
        The binding node to encode.

        Note that the adapter is dispatched on the pair
        `(binding.base.domain, binding.domain)`.

    `state` (:class:`EncodingState`)
        The current state of the encoding process.

    Aliases:

    `base` (:class:`htsql.tr.binding.Binding`)
        An alias for `binding.base`; the operand of the cast expression.

    `domain` (:class:`htsql.domain.Domain`)
        An alias for `binding.domain`; the target domain.
    """

    adapts(Domain, Domain)

    @classmethod
    def dispatch(interface, binding, *args, **kwds):
        # We override the standard extract of the dispatch key, which
        # returns the type of the first argument(s).  For `Convert`,
        # the dispatch key is the pair of the origin and the target domains.
        assert isinstance(binding, CastBinding)
        return (type(binding.base.domain), type(binding.domain))

    def __init__(self, binding, state):
        assert isinstance(binding, CastBinding)
        assert isinstance(state, EncodingState)
        self.binding = binding
        self.base = binding.base
        self.domain = binding.domain
        self.state = state

    def __call__(self):
        # A final check to eliminate conversion when the origin and
        # the target domains are the same.  It is likely no-op since
        # this case should be already handled.
        if self.base.domain == self.domain:
            return self.state.encode(self.base)
        # The default implementation complains that the conversion is
        # not admissible.
        raise EncodeError("inadmissible conversion", self.binding.mark)


class ConvertUntyped(Convert):
    # Validate and convert untyped literals.

    adapts(UntypedDomain, Domain)

    def __call__(self):
        # The base binding is of untyped domain, however it does not have
        # to be an instance of `LiteralBinding` since the actual literal node
        # could be wrapped by decorators.  However after we encode the node,
        # the decorators are gone and the result must be a `LiteralCode`
        # The domain should remain the same too.
        # FIXME: the literal could possibly be wrapped into `ScalarUnit`
        # if the literal binding was rescoped.
        base = self.state.encode(self.base)
        assert isinstance(base, (LiteralCode, ScalarUnit))
        assert isinstance(base.domain, UntypedDomain)
        # Unwrap scalar units from the literal code.
        wrappers = []
        while isinstance(base, ScalarUnit):
            wrappers.append(base)
            base = base.code
        assert isinstance(base, LiteralCode)
        # If the operand is a scalar unit,
        # Convert the serialized literal value to a Python object; raises
        # a `ValueError` if the literal is not in a valid format.
        try:
            value = self.domain.parse(base.value)
        except ValueError, exc:
            raise EncodeError(str(exc), self.binding.mark)
        # Generate a new literal node with the converted value and
        # the target domain.
        code = LiteralCode(value, self.domain, self.binding)
        # If necessary, wrap the literal back into scalar units.
        while wrappers:
            wrapper = wrappers.pop()
            code = wrapper.clone(code=code)
        return code


class ConvertToItself(Convert):
    # Eliminate redundant conversions.

    adapts_many((BooleanDomain, BooleanDomain),
                (IntegerDomain, IntegerDomain),
                (FloatDomain, FloatDomain),
                (DecimalDomain, DecimalDomain),
                (StringDomain, StringDomain),
                (DateDomain, DateDomain),
                (TimeDomain, TimeDomain),
                (DateTimeDomain, DateTimeDomain))
    # FIXME: do we need `EnumDomain` here?

    def __call__(self):
        # Encode and return the operand of the cast; drop the cast node itself.
        return self.state.encode(self.binding.base)


class ConvertTupleToBoolean(Convert):
    # Converts a tuple expression to a conditional expression.

    adapts(TupleDomain, BooleanDomain)

    def __call__(self):
        # When the binding domain is tuple, we assume that the binding
        # represents some flow.  In this case, Boolean cast produces
        # an expression which is `FALSE` when the flow is empty and
        # `TRUE` otherwise.  The actual expression is:
        #   `!is_null(unit)`,
        # where `unit` is some non-nullable function on the flow.

        # Translate the operand to a flow node.
        flow = self.state.relate(self.base)
        # A `TRUE` literal.
        true_literal = LiteralCode(True, coerce(BooleanDomain()), self.binding)
        # A `TRUE` constant as a function on the flow.
        unit = ScalarUnit(true_literal, flow, self.binding)
        # Return `!is_null(unit)`.
        return FormulaCode(IsNullSig(-1), coerce(BooleanDomain()),
                           self.binding, op=unit)


class ConvertStringToBoolean(Convert):
    # Convert a string expression to a conditional expression.

    adapts(StringDomain, BooleanDomain)

    def __call__(self):
        # A `NULL` value and an empty string are converted to `FALSE`,
        # any other string value is converted to `TRUE`.

        # Encode the operand of the cast.
        code = self.state.encode(self.base)
        # An empty string.
        empty_literal = LiteralCode('', self.base.domain, self.binding)
        # Construct: `null_if(base,'')`.
        code = FormulaCode(NullIfSig(), self.base.domain, self.binding,
                           lop=code, rop=empty_literal)
        # Construct: `!is_null(null_if(base,''))`.
        code = FormulaCode(IsNullSig(-1), self.domain, self.binding,
                           op=code)
        # Return `!is_null(null_if(base,''))`.
        return code


class ConvertToBoolean(Convert):
    # Convert an expression of any type to a conditional expression.

    adapts_many((NumberDomain, BooleanDomain),
                (EnumDomain, BooleanDomain),
                (DateDomain, BooleanDomain),
                (TimeDomain, BooleanDomain),
                (DateTimeDomain, BooleanDomain),
                (OpaqueDomain, BooleanDomain))
    # Note: we include the opaque domain here to ensure that any
    # data type could be converted to Boolean.  However this may
    # lead to unintuitive results.

    def __call__(self):
        # A `NULL` value is converted to `FALSE`; any other value is
        # converted to `TRUE`.

        # Construct and return `!is_null(base)`.
        return FormulaCode(IsNullSig(-1), self.domain, self.binding,
                           op=self.state.encode(self.base))


class ConvertToString(Convert):
    # Convert an expression to a string.

    adapts_many((BooleanDomain, StringDomain),
                (NumberDomain, StringDomain),
                (EnumDomain, StringDomain),
                (DateDomain, StringDomain),
                (TimeDomain, StringDomain),
                (DateTimeDomain, StringDomain),
                (OpaqueDomain, StringDomain))
    # Note: we assume we could convert any opaque data type to string;
    # it is risky but convenient.

    def __call__(self):
        # We generate a cast code node leaving it to the serializer
        # to specialize on the origin data type.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class ConvertToInteger(Convert):
    # Convert an expression to an integer value.

    adapts_many((DecimalDomain, IntegerDomain),
                (FloatDomain, IntegerDomain),
                (StringDomain, IntegerDomain))

    def __call__(self):
        # We leave conversion from literal values to the database
        # engine even though we could handle it here because the
        # conversion may be engine-specific.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class ConvertToDecimal(Convert):
    # Convert an expression to a decimal value.

    adapts_many((IntegerDomain, DecimalDomain),
                (FloatDomain, DecimalDomain),
                (StringDomain, DecimalDomain))

    def __call__(self):
        # Encode the operand of the cast.
        code = self.state.encode(self.base)
        # Handle conversion from an integer literal manually.
        # We do not handle conversion from other literal types
        # because it may be engine-specific.
        if isinstance(code, LiteralCode):
            if isinstance(code.domain, IntegerDomain):
                if code.value is None:
                    return code.clone(domain=self.domain)
                else:
                    value = decimal.Decimal(code.value)
                    return code.clone(value=value, domain=self.domain)
        # For the regular case, generate an appropriate cast node.
        return CastCode(code, self.domain, self.binding)


class ConvertToFloat(Convert):
    # Convert an expression to a float value.

    adapts_many((IntegerDomain, FloatDomain),
                (DecimalDomain, FloatDomain),
                (StringDomain, FloatDomain))

    def __call__(self):
        # Encode the operand of the cast.
        code = self.state.encode(self.base)
        # Handle conversion from an integer and decimal literals manually.
        # We do not handle conversion from other literal types because it
        # may be engine-specific.
        if isinstance(code, LiteralCode):
            if isinstance(code.domain, (IntegerDomain, DecimalDomain)):
                if code.value is None:
                    return code.clone(domain=self.domain)
                else:
                    value = float(code.value)
                    return code.clone(value=value, domain=self.domain)
        # For the regular case, generate an appropriate cast node.
        return CastCode(code, self.domain, self.binding)


class ConvertToDate(Convert):
    # Convert an expression to a date value.

    adapts_many((StringDomain, DateDomain),
                (DateTimeDomain, DateDomain))

    def __call__(self):
        # We leave conversion from literal values to the database
        # engine even though we could handle it here because the
        # conversion may be engine-specific.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class ConvertToTime(Convert):
    # Convert an expression to a time value.

    adapts_many((StringDomain, TimeDomain),
                (DateTimeDomain, TimeDomain))

    def __call__(self):
        # Leave conversion to the database engine.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class ConvertToDateTime(Convert):
    # Convert an expression to a datetime value.

    adapts_many((StringDomain, DateTimeDomain),
                (DateDomain, DateTimeDomain))

    def __call__(self):
        # Leave conversion to the database engine.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class EncodeRescoping(Encode):

    adapts(RescopingBinding)

    def __call__(self):
        # Wrap the base expression into a scalar unit.
        code = self.state.encode(self.binding.base)
        flow = self.state.relate(self.binding.scope)
        return ScalarUnit(code, flow, self.binding)


class EncodeFormula(Encode):

    adapts(FormulaBinding)

    def __call__(self):
        # Delegate the translation to the `EncodeBySignature` adapter.
        encode = EncodeBySignature(self.binding, self.state)
        return encode()


class RelateFormula(Relate):

    adapts(FormulaBinding)

    def __call__(self):
        # Delegate the translation to the `RelateBySignature` adapter.
        relate = RelateBySignature(self.binding, self.state)
        return relate()


class EncodeBySignatureBase(Adapter):
    """
    Translates a formula node.

    This is a base class for the two encoding adapters:
    :class:`EncodeBySignature` and :class:`RelateBySignature`;
    it encapsulates methods and attributes shared between these adapters.

    The adapter accepts a binding formula node and is polymorphic
    on the formula signature.

    `binding` (:class:`htsql.tr.binding.FormulaBinding`)
        The formula node to encode.

    `state` (:class:`EncodingState`)
        The current state of the encoding process.

    Aliases:

    `signature` (:class:`htsql.tr.signature.Signature`)
        The signature of the formula.

    `domain` (:class:`htsql.tr.domain.Domain`)
        The co-domain of the formula.

    `arguments` (:class:`htsql.tr.signature.Bag`)
        The arguments of the formula.
    """

    adapts(Signature)

    @classmethod
    def dispatch(interface, binding, *args, **kwds):
        # We need to override `dispatch` since the adapter is polymorphic
        # not on the type of the node itself, but on the type of the
        # node signature.
        assert isinstance(binding, FormulaBinding)
        return (type(binding.signature),)

    def __init__(self, binding, state):
        assert isinstance(binding, FormulaBinding)
        assert isinstance(state, EncodingState)
        self.binding = binding
        self.state = state
        # Extract commonly used attributes of the node.
        self.signature = binding.signature
        self.domain = binding.domain
        self.arguments = binding.arguments


class EncodeBySignature(EncodeBySignatureBase):
    """
    Translates a formula binding to a code node.

    This is an auxiliary adapter used to encode
    class:`htsql.tr.binding.FormulaBinding` nodes.  The adapter is
    polymorphic on the formula signature.

    Unless overridden, the adapter encodes the arguments of the formula
    and generates a new formula code with the same signature.
    """

    def __call__(self):
        # Encode the arguments of the formula.
        arguments = self.arguments.map(self.state.encode)
        # Produce a formula code with the same signature.
        return FormulaCode(self.signature,
                           self.domain,
                           self.binding,
                           **arguments)


class RelateBySignature(EncodeBySignatureBase):
    """
    Translates a formula binding to a flow node.

    This is an auxiliary adapter used to relate
    class:`htsql.tr.binding.FormulaBinding` nodes.  The adapter is
    polymorphic on the formula signature.

    Unless overridden, the adapter generates an error.
    """

    def __call__(self):
        # Override in subclasses for formulas that generate flow nodes.
        raise EncodeError("expected a valid flow expression",
                          self.binding.mark)


class EncodeWrapping(Encode):

    adapts_many(WrappingBinding)

    def __call__(self):
        # Delegate the adapter to the wrapped binding.
        return self.state.encode(self.binding.base)


class RelateWrapping(Relate):
    """
    Translates a wrapper binding to a flow node.
    """

    adapts_many(WrappingBinding)

    def __call__(self):
        # Delegate the adapter to the wrapped binding.
        return self.state.relate(self.binding.base)


def encode(binding, state=None):
    """
    Encodes the given binding to an expression node.

    Returns a :class:`htsql.tr.flow.Expression` instance (in most cases,
    a :class:`htsql.tr.flow.Code` instance).

    `binding` (:class:`htsql.tr.binding.Binding`)
        The binding node to encode.

    `state` (:class:`EncodingState` or ``None``)
        The encoding state to use.  If not set, a new encoding state
        is instantiated.
    """
    # Create a new encoding state if necessary.
    if state is None:
        state = EncodingState()
    # Realize and apply the `Encode` adapter.
    encode = Encode(binding, state)
    return encode()


def relate(binding, state=None):
    """
    Encodes the given binding to a data flow node.

    Returns a :class:`htsql.tr.flow.Flow` instance.

    `binding` (:class:`htsql.tr.binding.Binding`)
        The binding node to encode.

    `state` (:class:`EncodingState` or ``None``)
        The encoding state to use.  If not set, a new encoding state
        is instantiated.
    """
    # Create a new encoding state if necessary.
    if state is None:
        state = EncodingState()
    # Realize and apply the `Relate` adapter.
    relate = Relate(binding, state)
    return relate()


