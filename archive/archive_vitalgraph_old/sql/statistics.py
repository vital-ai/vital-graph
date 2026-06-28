"""Statistical summary of store statements mixin"""
import logging
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import func

_logger = logging.getLogger(__name__)


def get_group_by_count(session, group_by_column):
    """
    Construct SQL query to get counts for distinct values using GROUP BY.

    Args:
        session (~sqlalchemy.orm.session.Session): session to query in
        group_by_column (~sqlalchemy.schema.Column): column to group by

    Returns:
        dict: dictionary mapping from value to count
    """
    _logger.info(f"🚀 get_group_by_count: FUNCTION STARTED with session={session}, group_by_column={group_by_column}")
    return dict(
        session.query(
            group_by_column,
            func.count(group_by_column)
        ).group_by(group_by_column).all()
    )


class StatisticsMixin:
    """ Has methods for statistics on stores """
    def statistics(self, asserted_statements=True, literals=True, types=True):
        """Store statistics."""
        _logger.info(f"🚀 StatisticsMixin.statistics: FUNCTION STARTED with asserted_statements={asserted_statements}, literals={literals}, types={types}")
        statistics = {
            "store": dict(total_num_statements=len(self)),
        }

        with self.engine.connect() as connection:
            session = Session(bind=connection)
            if asserted_statements:
                table = self.tables["asserted_statements"]
                group_by_column = table.c.predicate
                statistics["asserted_statements"] = get_group_by_count(session, group_by_column)
            if literals:
                table = self.tables["literal_statements"]
                group_by_column = table.c.predicate
                statistics["literals"] = get_group_by_count(session, group_by_column)
            if types:
                table = self.tables["type_statements"]
                group_by_column = table.c.klass
                statistics["types"] = get_group_by_count(session, group_by_column)

        return statistics
