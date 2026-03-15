"""Tests for arkiv.render — schema-to-markdown rendering."""

from arkiv.schema import SchemaEntry, CollectionSchema
from arkiv.render import render_schema_summary, render_schema_detail, inject_schema_block


BEGIN = "<!-- arkiv:schema:begin -->"
END = "<!-- arkiv:schema:end -->"


class TestRenderSchemaSummary:
    def test_single_collection(self):
        schemas = {
            "conversations": CollectionSchema(
                record_count=150,
                metadata_keys={
                    "role": SchemaEntry(type="string", count=150),
                    "source": SchemaEntry(type="string", count=150),
                },
            ),
        }
        result = render_schema_summary(schemas)
        lines = result.strip().splitlines()
        # Sentinels
        assert lines[0] == BEGIN
        assert lines[-1] == END
        # Header row
        assert "Collection" in lines[1]
        assert "Records" in lines[1]
        assert "Keys" in lines[1]
        # Data row
        data_lines = [l for l in lines if "conversations" in l]
        assert len(data_lines) == 1
        assert "150" in data_lines[0]
        assert "role" in data_lines[0]
        assert "source" in data_lines[0]

    def test_multiple_collections_preserves_order(self):
        schemas = {
            "bookmarks": CollectionSchema(
                record_count=20,
                metadata_keys={
                    "url": SchemaEntry(type="string", count=20),
                },
            ),
            "conversations": CollectionSchema(
                record_count=150,
                metadata_keys={
                    "role": SchemaEntry(type="string", count=150),
                },
            ),
        }
        result = render_schema_summary(schemas)
        lines = result.strip().splitlines()
        data_lines = [l for l in lines if "|" in l and "Collection" not in l and "---" not in l]
        # bookmarks should come before conversations (dict order)
        bookmark_idx = next(i for i, l in enumerate(data_lines) if "bookmarks" in l)
        convo_idx = next(i for i, l in enumerate(data_lines) if "conversations" in l)
        assert bookmark_idx < convo_idx

    def test_empty_schemas(self):
        result = render_schema_summary({})
        assert BEGIN in result
        assert END in result
        # Should still have sentinels but no data rows
        lines = result.strip().splitlines()
        data_lines = [l for l in lines if "|" in l and "Collection" not in l and "---" not in l]
        assert len(data_lines) == 0


class TestRenderSchemaDetail:
    def test_low_cardinality_shows_values(self):
        schema = CollectionSchema(
            record_count=100,
            metadata_keys={
                "role": SchemaEntry(
                    type="string", count=100, values=["user", "assistant"]
                ),
            },
        )
        result = render_schema_detail(schema)
        assert "user" in result
        assert "assistant" in result

    def test_high_cardinality_shows_example(self):
        schema = CollectionSchema(
            record_count=100,
            metadata_keys={
                "id": SchemaEntry(
                    type="string", count=100, example="abc-123"
                ),
            },
        )
        result = render_schema_detail(schema)
        assert "abc-123" in result
        assert "*e.g.," in result

    def test_description_column_conditional(self):
        # No descriptions -> no Description column
        schema_no_desc = CollectionSchema(
            record_count=10,
            metadata_keys={
                "role": SchemaEntry(type="string", count=10, values=["user"]),
            },
        )
        result_no_desc = render_schema_detail(schema_no_desc)
        header_line = [l for l in result_no_desc.splitlines() if "Key" in l][0]
        assert "Description" not in header_line

        # With description -> Description column present
        schema_with_desc = CollectionSchema(
            record_count=10,
            metadata_keys={
                "role": SchemaEntry(
                    type="string", count=10, values=["user"],
                    description="Speaker identity",
                ),
            },
        )
        result_with_desc = render_schema_detail(schema_with_desc)
        header_line = [l for l in result_with_desc.splitlines() if "Key" in l][0]
        assert "Description" in header_line
        assert "Speaker identity" in result_with_desc

    def test_sentinels_present(self):
        schema = CollectionSchema(
            record_count=5,
            metadata_keys={
                "tag": SchemaEntry(type="string", count=5, values=["a"]),
            },
        )
        result = render_schema_detail(schema)
        assert result.strip().startswith(BEGIN)
        assert result.strip().endswith(END)

    def test_no_values_or_example_shows_empty(self):
        schema = CollectionSchema(
            record_count=10,
            metadata_keys={
                "data": SchemaEntry(type="object", count=10),
            },
        )
        result = render_schema_detail(schema)
        # The values column should be effectively empty for this entry
        lines = [l for l in result.splitlines() if "data" in l and "|" in l]
        assert len(lines) == 1
        # Split the row by | and check the values cell is empty/whitespace
        cells = lines[0].split("|")
        # Values column is the 4th cell (index 4: empty, Key, Type, Count, Values, ...)
        values_cell = cells[4].strip()
        assert values_cell == ""


class TestInjectSchemaBlock:
    def test_append_to_empty_body(self):
        block = f"{BEGIN}\nsome content\n{END}"
        result = inject_schema_block("", block)
        assert block in result

    def test_append_to_existing_body(self):
        body = "# My Archive\n\nSome description."
        block = f"{BEGIN}\ntable here\n{END}"
        result = inject_schema_block(body, block)
        assert result.startswith("# My Archive")
        assert "Some description." in result
        assert block in result

    def test_replace_existing_sentinels(self):
        old_block = f"{BEGIN}\nold content\n{END}"
        body = f"# Title\n\n{old_block}\n\nFooter text."
        new_block = f"{BEGIN}\nnew content\n{END}"
        result = inject_schema_block(body, new_block)
        assert "old content" not in result
        assert "new content" in result
        assert "# Title" in result
        assert "Footer text." in result

    def test_preserves_prose_outside_sentinels(self):
        body = f"Header prose.\n\n{BEGIN}\nstale data\n{END}\n\nFooter prose."
        new_block = f"{BEGIN}\nfresh data\n{END}"
        result = inject_schema_block(body, new_block)
        assert "Header prose." in result
        assert "Footer prose." in result
        assert "stale data" not in result
        assert "fresh data" in result
