"""Small versioned recipe registry loaded independently of the working directory."""
import json
from importlib.resources import files


def list_recipes():
    result = json.loads(files('simscene.recipes').joinpath('data/recipes.json').read_text())
    # Fixed examples are separate from role recipes accepted by compile_recipe.
    result['fixed_examples'] = list_examples()['examples']
    return result


def list_examples():
    """List model-free, pinned example inputs; this never asserts a new run passed."""
    return json.loads(files('simscene.recipes').joinpath('data/fixed-examples.json').read_text())


def get_recipe(recipe_id):
    for recipe in list_recipes()['recipes']:
        if recipe['recipe_id'] == recipe_id:
            return recipe
    raise ValueError('unknown recipe; available: ' + ', '.join(r['recipe_id'] for r in list_recipes()['recipes']))
