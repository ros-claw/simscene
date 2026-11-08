"""Asset preparation keeps USD/Isaac imports inside isolated SDK workers."""
from .profiles import PreparationError, preparation_key, validate_parameters


def prepare_acquired(acquired, profile, parameters, target, output_dir, *, app=None):
    from .usd_layers import prepare_acquired as prepare
    return prepare(acquired, profile, parameters, target, output_dir, app=app)

__all__ = ['PreparationError', 'preparation_key', 'validate_parameters', 'prepare_acquired']
