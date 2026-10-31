import enum


class Zone(enum.StrEnum):
    """The fixed set of restaurant zones that findings, areas, and dashboards group by: the
    zones of Maggiano's GoCanvas IPM form plus those of Chipotle's RiskGate form that don't fold
    into them. Stored as these values (check constraints list them; changing the set needs a
    migration)."""

    exterior_perimeter = "exterior_perimeter"
    dumpster_waste = "dumpster_waste"
    receiving_delivery = "receiving_delivery"
    dry_food_storage = "dry_food_storage"
    food_preparation = "food_preparation"
    service_line = "service_line"
    dishwashing_drains = "dishwashing_drains"
    bar_beverage = "bar_beverage"
    dining_guest = "dining_guest"
    restrooms = "restrooms"
    offices_employee = "offices_employee"
    mechanical_utility = "mechanical_utility"
    basement = "basement"
    ceiling_voids = "ceiling_voids"
    shared_structures = "shared_structures"
    other = "other"


def zone_check(column: str) -> str:
    """A check constraint's SQL limiting `column` to the zones (or null)."""
    return f"{column} IN ({', '.join(repr(z.value) for z in Zone)})"


# Display names used until an operator sets its own (zone_labels).
DEFAULT_ZONE_NAMES: dict[Zone, str] = {
    Zone.exterior_perimeter: "Exterior Perimeter",
    Zone.dumpster_waste: "Dumpster & Waste",
    Zone.receiving_delivery: "Receiving & Delivery",
    Zone.dry_food_storage: "Dry & Food Storage",
    Zone.food_preparation: "Food Preparation",
    Zone.service_line: "Service & Cook Line",
    Zone.dishwashing_drains: "Dishwashing & Drains",
    Zone.bar_beverage: "Bar & Beverage",
    Zone.dining_guest: "Dining & Guest Areas",
    Zone.restrooms: "Restrooms",
    Zone.offices_employee: "Offices & Employee Areas",
    Zone.mechanical_utility: "Mechanical & Utility",
    Zone.basement: "Basement",
    Zone.ceiling_voids: "Ceiling Voids & Paneling",
    Zone.shared_structures: "Shared Structures",
    Zone.other: "Other",
}
