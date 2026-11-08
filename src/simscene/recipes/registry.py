"""Small versioned recipe registry loaded independently of the working directory."""
import json
from importlib.resources import files


def list_recipes():
    return json.loads(files('simscene.recipes').joinpath('data/recipes.json').read_text())


def get_recipe(recipe_id):
    for recipe in list_recipes()['recipes']:
        if recipe['recipe_id'] == recipe_id:
            return recipe
    raise ValueError('unknown recipe; available: ' + ', '.join(r['recipe_id'] for r in list_recipes()['recipes']))
