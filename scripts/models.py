"""The one model the narration checker was validated with. Change it here, nowhere else."""

TESTED_MODEL = 'claude-opus-5-5'


def model_status(model):
    return 'tested' if model == TESTED_MODEL else 'unvalidated'
