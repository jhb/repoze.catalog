import bisect
import heapq
from itertools import islice

from zope.interface import implements

from zope.index.field import FieldIndex

from repoze.catalog.interfaces import ICatalogIndex
from repoze.catalog.indexes.common import CatalogIndex

_marker = []

FWSCAN = 'fwscan'
NBEST = 'nbest'
TIMSORT = 'timsort'

class CatalogFieldIndex(CatalogIndex, FieldIndex):
    implements(ICatalogIndex)

    def unindex_doc(self, docid):
        """See interface IInjection.

        Base class overridden to be able to unindex None values. """
        rev_index = self._rev_index
        value = rev_index.get(docid, _marker)
        if value is _marker:
            return # not in index

        del rev_index[docid]

        try:
            set = self._fwd_index[value]
            set.remove(docid)
        except KeyError:
            # This is fishy, but we don't want to raise an error.
            # We should probably log something.
            # but keep it from throwing a dirty exception
            set = 1

        if not set:
            del self._fwd_index[value]

        self._num_docs.change(-1)
                
    def sort(self, docids, reverse=False, limit=None, sort_type=None):
        if limit is not None:
            limit = int(limit)
            if limit < 1:
                raise ValueError('limit must be 1 or greater')

        if not docids:
            return []
            
        numdocs = self._num_docs.value
        if not numdocs:
            return []

        if reverse:
            return self.sort_reverse(docids, limit, numdocs, sort_type)
        else:
            return self.sort_forward(docids, limit, numdocs, sort_type)

    def sort_forward(self, docids, limit, numdocs, sort_type=None):

        rev_index = self._rev_index
        fwd_index = self._fwd_index

        rlen = len(docids)

        if sort_type is None:
            # XXX this needs work.  See
            # http://www.zope.org/Members/Caseman/ZCatalog_for_2.6.1
            # for an overview of why we bother doing all this work to
            # choose the right sort algorithm.
            docratio = rlen / float(numdocs)
            limitratio = rlen / float(limit)

            if limit < 300:
                # at very low limits, nbest tends to beat either fwscan
                # or timsort
                sort_type = NBEST

            elif not limit or docratio > .25:
                # forward scan tends to beat nbest or timsort reliably
                # when there's no limit or when the rlen is greater
                # than a quarter of the number of documents in the
                # index
                sort_type = FWSCAN

            elif docratio > .015625:
                # depending on the limit ratio, forward scan still has
                # a chance to win over nbest or timsort even if the
                # rlen is smaller than a quarter of the number of
                # documents in the index, beginning at a docratio of
                # 1024/65536.0 (.015625).  XXX It'd be nice to figure
                # out a more concise way to express this.
                if .0313 >= docratio > .051625 and limitratio < .0025:
                    sort_type = FWSCAN
                elif .0625 >= docratio > .0313 and limitratio < .001:
                    sort_type = FWSCAN
                elif .125 >= docratio > .0625 and limitratio < .008:
                    sort_type = FWSCAN
                elif .25 >= docratio > .125 and limitratio < .0625:
                    sort_type = FWSCAN

            else:
                sort_type = TIMSORT

        if sort_type == FWSCAN:
            return self.scan_forward(docids, limit)
        elif sort_type == NBEST:
            return self.nbest_ascending(docids, limit)
        elif sort_type == TIMSORT:
            return self.timsort_ascending(docids, limit)
        else:
            raise ValueError('Unknown sort type %s' % sort_type)

    def sort_reverse(self, docids, limit, numdocs, sort_type=None):
        if sort_type is None:
            # XXX this needs work.  See
            # http://www.zope.org/Members/Caseman/ZCatalog_for_2.6.1
            # for an overview of why we bother doing all this work to
            # choose the right sort algorithm.

            rlen = len(docids)
            if limit:
                if (limit < 300) or (limit/float(rlen)) > 0.09:
                    sort_type = NBEST
                else:
                    sort_type = TIMSORT
            else:
                sort_type = TIMSORT

        if sort_type == NBEST:
            return self.nbest_descending(docids, limit)
        elif sort_type == TIMSORT:
            return self.timsort_descending(docids, limit)
        else:
            raise ValueError('Unknown sort type %s' % sort_type)
 
    def scan_forward(self, docids, limit=None):
        fwd_index = self._fwd_index

        sets = []
        n = 0
        for set in fwd_index.values():
            for docid in set:
                if docid in docids:
                    n+=1
                    yield docid
                    if limit and n >= limit:
                        raise StopIteration

    def nbest_ascending(self, docids, limit):
        if limit is None:
            raise RuntimeError, 'n-best used without limit'

        # lifted from heapq.nsmallest

        h = nsort(docids, self._rev_index)
        it = iter(h)
        result = sorted(islice(it, 0, limit))
        if not result:
            raise StopIteration
        insort = bisect.insort
        pop = result.pop
        los = result[-1]    # los --> Largest of the nsmallest
        for elem in it:
            if los <= elem:
                continue
            insort(result, elem)
            pop()
            los = result[-1]

        for value, docid in result:
            yield docid

    def nbest_descending(self, docids, limit):
        if limit is None:
            raise RuntimeError, 'N-Best used without limit'
        iterable = nsort(docids, self._rev_index)
        for value, docid in heapq.nlargest(limit, iterable):
            yield docid
    
    def timsort_ascending(self, docids, limit):
        return self._timsort(docids, limit, reverse=False)

    def timsort_descending(self, docids, limit):
        return self._timsort(docids, limit, reverse=True)

    def _timsort(self, docids, limit=None, reverse=False):
        n = 0
        marker = _marker
        _missing = []

        def get(k, rev_index=self._rev_index, marker=marker):
            v = rev_index.get(k, marker)
            if v is marker:
                _missing.append(k)
            return v
        
        for docid in sorted(docids, key=get, reverse=reverse):
            if docid in _missing:
                # skip docids not in this index
                continue
            n += 1
            yield docid
            if limit and n >= limit:
                raise StopIteration

def nsort(docids, rev_index):
    for docid in docids:
        try:
            yield (rev_index[docid], docid)
        except KeyError:
            continue

