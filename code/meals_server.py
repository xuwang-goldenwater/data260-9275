"""
HW5 Part 2A - TheMealDB MCP server ("meals"), run over STDIO.

    make inspect-meals
    (= npx @modelcontextprotocol/inspector python code/meals_server.py)

Tools: search_meals_by_name, meals_by_ingredient, meal_details, random_meal
API:   https://www.themealdb.com/api/json/v1/1/...   (public test key "1")

STDIO rule: stdout carries the JSON-RPC messages between this server and its
client, so nothing else may be written there - no print(). All logging goes
to stderr.
"""
import logging
import sys
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

API_BASE = "https://www.themealdb.com/api/json/v1/1"
TIMEOUT_SECONDS = 10.0

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s meals: %(message)s")
log = logging.getLogger("meals")

mcp = FastMCP("meals")


def fetch(endpoint: str, params: dict | None = None) -> list[dict]:
    """GET one TheMealDB endpoint and return its "meals" list.

    TheMealDB answers {"meals": null} when nothing matches; that becomes [].
    A network problem or a body that is not JSON raises RuntimeError with a
    short message, which the MCP client shows as the tool's error.
    """
    url = f"{API_BASE}/{endpoint}"
    log.info("GET %s %s", url, params or "")
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        log.error("request failed: %r", exc)
        raise RuntimeError(f"TheMealDB request failed: {exc}") from exc
    except ValueError as exc:
        log.error("response was not JSON")
        raise RuntimeError("TheMealDB returned a response that is not JSON") from exc

    meals = payload.get("meals") if isinstance(payload, dict) else None
    return meals if isinstance(meals, list) else []


def result(meals: list[dict]) -> dict[str, Any]:
    """The shape every list tool returns: a count, a short message, the meals."""
    message = f"{len(meals)} match(es)" if meals else "no matches"
    return {"count": len(meals), "message": message, "meals": meals}


# ---- tool 1 -------------------------------------------------------------------

@mcp.tool()
def search_meals_by_name(
    query: Annotated[str, Field(min_length=1, description="Part of a meal name, e.g. Arrabiata")],
    limit: Annotated[int, Field(ge=1, le=25, description="How many meals to return (1-25)")] = 5,
) -> dict[str, Any]:
    """Search TheMealDB by meal name. Each meal has id, name, area (cuisine),
    category and thumb; pass the id to meal_details for the full recipe."""
    meals = fetch("search.php", {"s": query})
    return result([
        {"id": m["idMeal"], "name": m["strMeal"], "area": m.get("strArea"),
         "category": m.get("strCategory"), "thumb": m.get("strMealThumb")}
        for m in meals[:limit]
    ])


# ---- tool 2 -------------------------------------------------------------------

@mcp.tool()
def meals_by_ingredient(
    ingredient: Annotated[str, Field(min_length=1, description="Main ingredient, e.g. chicken")],
    limit: Annotated[int, Field(ge=1, le=50, description="How many meals to return (1-50)")] = 12,
) -> dict[str, Any]:
    """List meals whose main ingredient is `ingredient`. Returns small cards
    (id, name, thumb); pass an id to meal_details for the full recipe."""
    # TheMealDB writes multi-word ingredients with underscores: chicken_breast
    meals = fetch("filter.php", {"i": ingredient.strip().replace(" ", "_")})
    return result([
        {"id": m["idMeal"], "name": m["strMeal"], "thumb": m.get("strMealThumb")}
        for m in meals[:limit]
    ])


# ---- tools 3 and 4 ------------------------------------------------------------

def full_meal(m: dict) -> dict[str, Any]:
    """One raw TheMealDB meal -> the detail shape that both tools below return.

    TheMealDB stores ingredients in 40 flat fields (strIngredient1..20 and
    strMeasure1..20) and pads the unused ones with "" or null. They are folded
    into one list of {name, measure}, skipping the empty slots.
    """
    ingredients = []
    for n in range(1, 21):
        name = (m.get(f"strIngredient{n}") or "").strip()
        measure = (m.get(f"strMeasure{n}") or "").strip()
        if name:
            ingredients.append({"name": name, "measure": measure})
    return {
        "id": m["idMeal"],
        "name": m["strMeal"],
        "category": m.get("strCategory"),
        "area": m.get("strArea"),
        "instructions": m.get("strInstructions"),
        "image": m.get("strMealThumb"),
        "source": m.get("strSource"),
        "youtube": m.get("strYoutube"),
        "ingredients": ingredients,
    }


@mcp.tool()
def meal_details(
    id: Annotated[str | int, Field(description="Meal id from one of the search tools, e.g. 52771")],
) -> dict[str, Any]:
    """Full recipe for one meal id: category, area, instructions, image, source,
    youtube and the ingredient list with measures."""
    meal_id = str(id).strip()
    if not meal_id.isdigit():
        raise ValueError(f"id must be a whole number such as 52771, got {id!r}")
    meals = fetch("lookup.php", {"i": meal_id})
    if not meals:
        return {"id": meal_id, "message": "no matches"}
    return full_meal(meals[0])


@mcp.tool()
def random_meal() -> dict[str, Any]:
    """One random meal, in the same shape as meal_details."""
    meals = fetch("random.php")
    if not meals:
        return {"message": "no matches"}
    return full_meal(meals[0])


if __name__ == "__main__":
    mcp.run(transport="stdio")
