# Getting Started with Acme Widgets

Acme Widgets is a sample product used to demonstrate the document knowledge base.

## Installation

Install the Acme Widgets CLI with `pip install acme-widgets`. The CLI requires
Python 3.11 or newer. After installing, run `acme init` in your project folder to
create a starter `acme.toml` configuration file.

## Creating your first widget

Run `acme new my-widget` to scaffold a widget. Each widget has a name, a size
(small, medium, or large), and a color. Sizes default to medium and colors
default to blue if you do not specify them.

## Running widgets

Use `acme run my-widget` to build and run a widget locally. Add `--watch` to
rebuild automatically when files change. Logs are written to `./.acme/logs/`.
