import argparse
import jinja2


def main():
    parser = argparse.ArgumentParser(description="Generate init script using jinja2 template")
    parser.add_argument("project", type=str, help="Project name with organization i.e. organization/project")
    parser.add_argument("feed", type=str, help="Feed name with artifacts")
    parser.add_argument("package", type=str, help="Package Name in PyPI Format i.e. name==version")
    parser.add_argument("template_path", type=str, help="Path to template file")
    parser.add_argument("output_path", type=str, help="Path to generated script")

    args = parser.parse_args()

    loader = jinja2.FileSystemLoader(searchpath="./")
    environment = jinja2.Environment(loader=loader)
    template = environment.get_template(name=args.template_path)
    output = template.render(
        project=args.project,
        feed=args.feed,
        package=args.package,
    )

    with (open(args.output_path, "w")) as f:
        f.write(output)


if __name__ == "__main__":
    main()
