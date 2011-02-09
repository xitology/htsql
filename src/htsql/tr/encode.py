#
# Copyright (c) 2006-2011, Prometheus Research, LLC
# Authors: Clark C. Evans <cce@clarkevans.com>,
#          Kirill Simonov <xi@resolvent.net>
#


"""
:mod:`htsql.tr.encode`
======================

This module implements the encoding process.
"""


from ..adapter import Adapter, adapts, adapts_many
from ..domain import (Domain, UntypedDomain, TupleDomain, BooleanDomain,
                      NumberDomain, IntegerDomain, DecimalDomain, FloatDomain,
                      StringDomain, EnumDomain, DateDomain, OpaqueDomain)
from .error import EncodeError
from .coerce import coerce
from .binding import (Binding, RootBinding, QueryBinding, SegmentBinding,
                      FreeTableBinding, AttachedTableBinding,
                      QuotientBinding, ComplementBinding, KernelBinding,
                      ColumnBinding, LiteralBinding, SieveBinding,
                      SortBinding, CastBinding, WrapperBinding,
                      DefinitionBinding, AliasBinding,
                      DirectionBinding, FormulaBinding)
from .code import (ScalarSpace, DirectProductSpace, FiberProductSpace,
                   QuotientSpace, ComplementSpace,
                   FilteredSpace, OrderedSpace,
                   QueryExpr, SegmentExpr, LiteralCode, FormulaCode,
                   CastCode, ColumnUnit, ScalarUnit, KernelUnit)
from .signature import Signature, IsNullSig, NullIfSig
import decimal


class EncodingState(object):
    """
    Encapsulates the (mutable) state of the encoding process.

    Currently encoding is a stateless process, but we will likely add
    extra state in the future.  The state is also used to store the
    cache of binding to space and binding to code translations.
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
        self.binding_to_space = {}

    def flush(self):
        """
        Clears the encoding state.
        """
        self.binding_to_code.clear()
        self.binding_to_state.clear()

    def encode(self, binding):
        """
        Encodes the given binding node to a code expression node.

        Returns a :class:`htsql.tr.code.Code` node (in some cases,
        a :class:`htsql.tr.code.Expression` node).

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
        Encodes the given binding node to a space expression node.

        Returns a :class:`htsql.tr.code.Space` node.

        `binding` (:class:`htsql.tr.binding.Binding`)
            The binding node to encode.
        """
        # When caching is enabled, we check if `binding` was
        # already encoded.  If not, we encode it and save the
        # result.
        if self.with_cache:
            if binding not in self.binding_to_space:
                space = relate(binding, self)
                self.binding_to_space[binding] = space
            return self.binding_to_space[binding]
        # Caching is disabled; return a new instance every time.
        return relate(binding, self)

    def direct(self, binding):
        """
        Extracts a direction modifier from the given binding.

        A direction modifier is set by post-fix ``+`` and ``-`` operators.
        The function returns ``+1`` for the ``+`` modifier (ascending order),
        ``-1`` for the ``-`` modifier (descending order), ``None`` if there
        are no modifiers.

        `binding` (:class:`htsql.tr.binding.Binding`)
            The binding node.
        """
        # FIXME: `Direct` does not really depend on the state, should
        # it still accept it?
        return direct(binding, self)


class EncodeBase(Adapter):
    """
    Applies an encoding adapter to a binding node.

    This is a base class for three encoding adapters: :class:`Encode`,
    :class:`Relate`, :class:`Direct`; it encapsulates methods and
    attributes shared between these adapters.

    The encoding process translates binding nodes to space and code
    nodes.  Space nodes represent ordered sets of rows; code nodes
    represent functions on spaces.  See :class:`htsql.tr.binding.Binding`,
    :class:`htsql.tr.code.Expression`, :class:`htsql.tr.code.Space`,
    :class:`htsql.tr.code.Code` for more details on the respective
    node types.

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

        Encode: (Binding, EncodingState) -> Code or Expression

    The adapter is polymorphic on the `Binding` argument.

    See :class:`htsql.tr.binding.Binding`, :class:`htsql.tr.code.Expression`,
    :class:`htsql.tr.code.Code` for detail on the respective nodes.

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
    Translates a binding node to a space expression node.

    This is an interface adapter; see subclasses for implementations.

    The :class:`Relate` adapter has the following signature::

        Relate: (Binding, EncodingState) -> Space

    The adapter is polymorphic on the `Binding` argument.

    See :class:`htsql.tr.binding.Binding` and :class:`htsql.tr.code.Space`
    for detail on the respective nodes.

    The adapter provides non-trivial implementations for subclasses
    of :class:`htsql.tr.binding.ChainBinding`; the `base` attributes
    are used to restore the structure of the space.
    """

    def __call__(self):
        # The default implementation generates an error.
        # FIXME: a better error message?
        raise EncodeError("expected a valid space expression",
                          self.binding.mark)


class Direct(EncodeBase):
    """
    Extracts a direction modifier from the given binding.

    A direction modifier is set by post-fix ``+`` and ``-`` operators.
    The function returns ``+1`` for the ``+`` modifier (ascending order),
    ``-1`` for the ``-`` modifier (descending order), ``None`` if there
    are no modifiers.

    This is an interface adapter; see subclasses for implementations.

    The :class:`Direct` adapter has the following signature::

        Direct: (Binding, EncodingState) -> +1 or -1 or None

    The adapter is polymorphic on the `Binding` argument.

    The adapter unwraps binding nodes looking for instances of
    :class:`htsql.tr.binding.DirectionBinding`, which represent
    direction modifiers.
    """

    def __call__(self):
        # The default implementation produces no modifier.
        return None


class EncodeQuery(Encode):
    """
    Encodes the top-level binding node :class:`htsql.tr.binding.QueryBinding`.

    Produces an instance of :class:`htsql.tr.code.QueryExpr`.
    """

    adapts(QueryBinding)

    def __call__(self):
        # Encode the segment node if it is provided.
        segment = None
        if self.binding.segment is not None:
            segment = self.state.encode(self.binding.segment)
        # Construct the expression node.
        return QueryExpr(segment, self.binding)


class EncodeSegment(Encode):
    """
    Encodes a segment binding node :class:`htsql.tr.binding.SegmentBinding`.

    Produces an instance of :class:`htsql.tr.code.SegmentExpr`.
    """

    adapts(SegmentBinding)

    def __call__(self):
        # The base is translated to the segment space.  Note that we still
        # need to extract and apply direction modifiers.
        space = self.state.relate(self.binding.base)
        # A list of pairs `(code, dir)` that contains extracted direction
        # modifiers and respective code nodes.
        order = []
        # The list of segment elements.
        elements = []
        # Encode each of the element binding at the same time extracting
        # direction modifiers.
        for binding in self.binding.elements:
            # Encode the node.
            element = self.state.encode(binding)
            elements.append(element)
            # Extract the direction modifier.
            direction = self.state.direct(binding)
            if direction is not None:
                order.append((element, direction))
        # If any direction modifiers are found, augment the segment space
        # by adding an explicit ordering node.
        if order:
            space = OrderedSpace(space, order, None, None, self.binding)
        # Construct the expression node.
        return SegmentExpr(space, elements, self.binding)


class RelateRoot(Relate):
    """
    Translates the root binding node to a space node.

    Returns a scalar space node :class:`htsql.tr.code.ScalarSpace`.
    """

    adapts(RootBinding)

    def __call__(self):
        # The root binding always originates the scalar space `I`.
        return ScalarSpace(None, self.binding)


class RelateFreeTable(Relate):
    """
    Translates a free table binding to a space node.

    Returns a direct product node :class:`htsql.tr.code.DirectProductSpace`.
    """

    adapts(FreeTableBinding)

    def __call__(self):
        # Generate a space node corresponding to the binding base.
        base = self.state.relate(self.binding.base)
        # Produce a direct product space between the base space and
        # the binding table: `base * table`.
        return DirectProductSpace(base, self.binding.table, self.binding)


class RelateAttachedTable(Relate):
    """
    Translates an attached table binding to a space node.

    Returns a fiber product node :class:`htsql.tr.code.FiberProductSpace`.
    """

    adapts(AttachedTableBinding)

    def __call__(self):
        # Generate a space node corresponding to the binding base.
        space = self.state.relate(self.binding.base)
        # The binding is attached to its base by a series of joins.
        # For each join, we produce a fiber product space:
        #   `base . target1 . target2 . ...`.
        for join in self.binding.joins:
            space = FiberProductSpace(space, join, self.binding)
        return space


class RelateSieve(Relate):
    """
    Translates a sieve binding to a space node.

    Returns a filtered space node :class:`htsql.tr.code.FilteredSpace`.
    """

    adapts(SieveBinding)

    def __call__(self):
        # Generate a space node corresponding to the binding base.
        space = self.state.relate(self.binding.base)
        # Encode the predicate expression.
        filter = self.state.encode(self.binding.filter)
        # Augment the base space with a filter: `base ? filter`.
        return FilteredSpace(space, filter, self.binding)


class DirectSieve(Direct):
    """
    Extracts the direction modifier from a sieve binding.
    """

    adapts(SieveBinding)

    def __call__(self):
        # We delegate the adapter to the binding base, ignoring the filter.
        # FIXME: It is controversal, but matches the `entitle` adapter.
        # Perhaps, we need to add a class attribute `is_passthrough`
        # (or a mixin class `PassthroughBinding`) to indicate bindings
        # that could delegate modifier extraction adapters?
        return self.state.direct(self.binding.base)


class RelateSort(Relate):
    """
    Translates a sort binding to a space node.

    Returns an ordered space node :class:`htsql.tr.code.OrderedSpace`.
    """

    adapts(SortBinding)

    def __call__(self):
        # Generate a space node corresponding to the binding base.
        space = self.state.relate(self.binding.base)
        # A list of pairs `(code, direction)` containing the expressions
        # by which the space is sorted and respective direction indicators.
        order = []
        # Iterate over ordering binding nodes.
        for binding in self.binding.order:
            # Encode the binding.
            code = self.state.encode(binding)
            # Extract the direction modifier; assume `+` if none.
            direction = self.state.direct(binding)
            if direction is None:
                direction = +1
            order.append((code, direction))
        # The slice indicators.
        limit = self.binding.limit
        offset = self.binding.offset
        # Produce an ordered space node over the base space:
        #   `base [e,...;offset:offset+limit]`.
        return OrderedSpace(space, order, limit, offset, self.binding)


class EncodeColumn(Encode):
    """
    Translates a column binding to a code node.

    Returns a column unit node :class:`htsql.tr.code.ColumnUnit`.
    """

    adapts(ColumnBinding)

    def __call__(self):
        # The binding base is translated to the space of the unit node.
        space = self.state.relate(self.binding.base)
        # Generate a column unit node.
        return ColumnUnit(self.binding.column, space, self.binding)


class RelateColumn(Relate):
    """
    Translates a column binding to a space node.

    Returns a fiber product node :class:`htsql.tr.code.FiberProductSpace` or
    raises an error.
    """

    adapts(ColumnBinding)

    def __call__(self):
        # If the column binding has an associated table binding node,
        # delegate the adapter to it.
        if self.binding.link is not None:
            return self.state.relate(self.binding.link)
        # Otherwise, let the parent produce an error message.
        return super(RelateColumn, self).__call__()


class RelateQuotient(Relate):

    adapts(QuotientBinding)

    def __call__(self):
        space = self.state.relate(self.binding.base)
        seed_space = self.state.relate(self.binding.seed)
        if space.spans(seed_space):
            raise EncodeError("a plural operand is required",
                              seed_space.mark)
        if not seed_space.spans(space):
            raise EncodeError("invalid plural operand",
                              seed_space.mark)
        kernel = [self.state.encode(binding)
                  for binding in self.binding.kernel]
        return QuotientSpace(space, seed_space, kernel, self.binding)


class RelateComplement(Relate):

    adapts(ComplementBinding)

    def __call__(self):
        space = self.state.relate(self.binding.base)
        return ComplementSpace(space, self.binding)


class EncodeKernel(Encode):

    adapts(KernelBinding)

    def __call__(self):
        space = self.state.relate(self.binding.base)
        return KernelUnit(self.binding.index, space, self.binding)


class EncodeLiteral(Encode):
    """
    Encodes a literal binding.

    Returns a literal code node :class:`htsql.tr.code.LiteralCode`.
    """

    adapts(LiteralBinding)

    def __call__(self):
        # Switch the class from `Binding` to `Code` keeping all attributes.
        return LiteralCode(self.binding.value, self.binding.domain,
                           self.binding)


class EncodeCast(Encode):
    """
    Encodes a cast binding.

    The actual encoding is performed by the :class:`Convert` adapter.
    """

    adapts(CastBinding)

    def __call__(self):
        # Delegate it to the `Convert` adapter.
        convert = Convert(self.binding, self.state)
        return convert()


class DirectCast(Direct):
    """
    Extracts a direction modifier from a cast binding.
    """

    adapts(CastBinding)

    def __call__(self):
        # The adapter is delegated to the binding base; we have to do it
        # because many expressions (including segment elements) are wrapped
        # with implicit cast nodes, which otherwise would mask any decorators.
        return self.state.direct(self.binding.base)


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
      generates a new :class:`htsql.tr.code.CastCode` node.

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
    """
    Validates and converts untyped literals.
    """

    adapts(UntypedDomain, Domain)

    def __call__(self):
        # The base binding is of untyped domain, however it does not have
        # to be an instance of `LiteralBinding` since the actual literal node
        # could be wrapped by decorators.  However after we encode the node,
        # the decorators are gone and the result must be a `LiteralCode`.
        # The domain should remain the same too.
        base = self.state.encode(self.base)
        assert isinstance(base, LiteralCode)
        assert isinstance(base.domain, UntypedDomain)
        # Convert the serialized literal value to a Python object; raises
        # a `ValueError` if the literal is not in a valid format.
        try:
            value = self.domain.parse(base.value)
        except ValueError, exc:
            raise EncodeError(str(exc), self.binding.mark)
        # Generate a new literal node with the converted value and
        # the target domain.
        return LiteralCode(value, self.domain, self.binding)


class ConvertToItself(Convert):
    """
    Eliminates redundant conversions.
    """
    adapts_many((BooleanDomain, BooleanDomain),
                (IntegerDomain, IntegerDomain),
                (FloatDomain, FloatDomain),
                (DecimalDomain, DecimalDomain),
                (StringDomain, StringDomain),
                (DateDomain, DateDomain))
    # FIXME: do we need `EnumDomain` here?

    def __call__(self):
        # Encode and return the operand of the cast.
        return self.state.encode(self.binding.base)


class ConvertTupleToBoolean(Convert):
    """
    Converts a tuple expression to a conditional expression.
    """

    adapts(TupleDomain, BooleanDomain)

    def __call__(self):
        # When the binding domain is tuple, we assume that the binding
        # represents some space.  In this case, Boolean cast produces
        # an expression which is `FALSE` when the space is empty and
        # `TRUE` otherwise.  The actual expression is:
        #   `!is_null(unit)`,
        # where `unit` is some non-nullable function on the space.

        # Translate the operand to a space node.
        space = self.state.relate(self.base)
        # A `TRUE` literal.
        true_literal = LiteralCode(True, coerce(BooleanDomain()), self.binding)
        # A `TRUE` constant as a function on the space.
        unit = ScalarUnit(true_literal, space, self.binding)
        # Return `!is_null(unit)`.
        return FormulaCode(IsNullSig(-1), coerce(BooleanDomain()),
                           self.binding, op=unit)


class ConvertStringToBoolean(Convert):
    """
    Converts a string expression to a conditional expression.
    """

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
    """
    Converts an expression of any type to a conditional expression.
    """

    adapts_many((NumberDomain, BooleanDomain),
                (EnumDomain, BooleanDomain),
                (DateDomain, BooleanDomain),
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
    """
    Convert an expression to a string.
    """

    adapts_many((BooleanDomain, StringDomain),
                (NumberDomain, StringDomain),
                (EnumDomain, StringDomain),
                (DateDomain, StringDomain),
                (OpaqueDomain, StringDomain))
    # Note: we assume we could convert any opaque data type to string;
    # it is risky but convenient.

    def __call__(self):
        # We generate a cast code node leaving it to the serializer
        # to specialize on the origin data type.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class ConvertToInteger(Convert):
    """
    Convert an expression to an integer value.
    """

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
    """
    Convert an expression to a decimal value.
    """

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
    """
    Convert an expression to a float value.
    """

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
    """
    Convert an expression to a date value.
    """

    adapts(StringDomain, DateDomain)

    def __call__(self):
        # We leave conversion from literal values to the database
        # engine even though we could handle it here because the
        # conversion may be engine-specific.
        return CastCode(self.state.encode(self.base), self.domain,
                        self.binding)


class EncodeFormula(Encode):
    """
    Translates a formula binding to a code node.

    The translation is specific to the formula signature and is implemented
    by the :class:`EncodeBySignature` adapter.
    """

    adapts(FormulaBinding)

    def __call__(self):
        # Delegate the translation to the `EncodeBySignature` adapter.
        encode = EncodeBySignature(self.binding, self.state)
        return encode()


class RelateFormula(Relate):
    """
    Translates a formula binding to a space node.

    The translation is specific to the formula signature and is implemented
    by the :class:`RelateBySignature` adapter.
    """

    adapts(FormulaBinding)

    def __call__(self):
        # Delegate the translation to the `RelateBySignature` adapter.
        relate = RelateBySignature(self.binding, self.state)
        return relate()


class DirectFormula(Direct):
    """
    Extracts a direction modifier from a formula binding.

    The extration is specific to the formula signature and is implemented
    by the :class:`DirectBySignature` adapter.
    """

    adapts(FormulaBinding)

    def __call__(self):
        # Delegate the extraction to the `DirectBySignature` adapter.
        direct = DirectBySignature(self.binding, self.state)
        return direct()


class EncodeBySignatureBase(Adapter):
    """
    Translates a formula node.

    This is a base class for three encoding adapters:
    :class:`EncodeBySignature`, :class:`RelateBySignature` and
    :class:`DirectBySignature`; it encapsulates methods and attributes
    shared between these adapters.

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
    Translates a formula binding to a space node.

    This is an auxiliary adapter used to relate
    class:`htsql.tr.binding.FormulaBinding` nodes.  The adapter is
    polymorphic on the formula signature.

    Unless overridden, the adapter generates an error.
    """

    def __call__(self):
        # Override in subclasses for formulas that generate space nodes.
        raise EncodeError("expected a valid space expression",
                          self.binding.mark)


class DirectBySignature(EncodeBySignatureBase):
    """
    Extracts a direction modifier from a formula node.

    This is an auxiliary adapter used to extract direction modifiers
    from class:`htsql.tr.binding.FormulaBinding` nodes.  The adapter is
    polymorphic on the formula signature.

    Unless overridden, the adapter returns no direction modifier.
    """

    def __call__(self):
        # Override in subclasses for formulas which may export non-trivial
        # direction modifier.
        return None


class EncodeWrapper(Encode):
    """
    Translates a wrapper binding to a code node.
    """

    adapts_many(WrapperBinding,
                DefinitionBinding)

    def __call__(self):
        # Delegate the adapter to the wrapped binding.
        return self.state.encode(self.binding.base)


class RelateWrapper(Relate):
    """
    Translates a wrapper binding to a space node.
    """

    adapts_many(WrapperBinding,
                DefinitionBinding)

    def __call__(self):
        # Delegate the adapter to the wrapped binding.
        return self.state.relate(self.binding.base)


class DirectWrapper(Direct):
    """
    Extracts a direction modifier from a wrapper binding.
    """

    adapts_many(WrapperBinding,
                DefinitionBinding)

    def __call__(self):
        # Delegate the adapter to the wrapped binding.
        return self.state.direct(self.binding.base)


class EncodeAlias(Encode):

    adapts(AliasBinding)

    def __call__(self):
        return self.state.encode(self.binding.binding)


class RelateAlias(Relate):

    adapts(AliasBinding)

    def __call__(self):
        return self.state.relate(self.binding.binding)


class DirectAlias(Direct):

    adapts(AliasBinding)

    def __call__(self):
        return self.state.direct(self.binding.binding)


class DirectDirection(Direct):
    """
    Extracts a direction modifier from a direction decorator.
    """

    adapts(DirectionBinding)

    def __call__(self):
        # The direction modifier specified by the decorator.
        direction = self.binding.direction
        # Here we handle nested decorators: `++` and `--` are
        # translated to `+`; `+-` and `-+` are translated to `-`.
        base_direction = self.state.direct(self.binding.base)
        if base_direction is not None:
            direction *= base_direction
        # Return the combined direction.
        return direction


def encode(binding, state=None):
    """
    Encodes the given binding to a code expression node.

    Returns a :class:`htsql.tr.code.Code` instance (in some cases,
    a :class:`htsql.tr.code.Expression` instance).

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
    Encodes the given binding to a space expression node.

    Returns a :class:`htsql.tr.code.Space` instance.

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


def direct(binding, state=None):
    """
    Extracts a direction modifier from the given binding.

    Returns

    - ``+1`` for the ``+`` modifier (ascending order);
    - ``-1`` for the ``-`` modifier (descending order);
    - ``None`` if there are no modifiers.

    `binding` (:class:`htsql.tr.binding.Binding`)
        The binding node.

    `state` (:class:`EncodingState` or ``None``)
        The encoding state to use.  If not set, a new encoding state
        is instantiated.
    """
    # Create a new encoding state if necessary.
    if state is None:
        state = EncodingState()
    # Realize and apply the `Direct` adapter.
    direct = Direct(binding, state)
    return direct()


