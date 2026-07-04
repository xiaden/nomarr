from nomarr.helpers.dto.tags_dto import Tag, Tags

tag1 = Tag(key="test", value=("test",))
tags1 = Tags(items=(tag1,))
print(tag1)
print(tags1)
