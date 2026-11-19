#include "trailstate.h"

#include <QFile>
#include <QTemporaryDir>
#include <QtLogging>

#include <cstdlib>

using namespace OsuCursor;

static void require(bool condition, const char *message)
{
    if (!condition) {
        qFatal("%s", message);
    }
}

static void write(const QTemporaryDir &directory, const QString &name, const QByteArray &bytes)
{
    QFile file(directory.filePath(name));
    require(file.open(QIODevice::WriteOnly), "Could not write test fixture");
    require(file.write(bytes) == bytes.size(), "Incomplete test fixture");
}

int main()
{
    QTemporaryDir directory;
    require(directory.isValid(), "Could not create test directory");
    bool invalid = true;
    require(!readTrail(directory.path(), invalid) && !invalid, "An absent state is normal");
    const QString state = QStringLiteral("state.json");
    const QString texture = QStringLiteral("trail-000000000000.rgba");
    write(directory, state, "{bad json}");
    require(!readTrail(directory.path(), invalid) && invalid, "Malformed JSON must be rejected");
    write(directory, state, R"({
      "version": 1, "theme": "osu-cursor-plasma-000000000000", "skin_cursor": null,
      "trail": {"file": "trail-000000000000.rgba", "width": 1, "height": 1,
                "display_width": 8, "display_height": 8, "interval": 4,
                "disjoint": false, "centre": true}
    })");
    require(!readTrail(directory.path(), invalid) && invalid, "A missing texture must be rejected");
    write(directory, texture, QByteArray(3, '\0'));
    require(!readTrail(directory.path(), invalid) && invalid, "Truncated texture must be rejected");
    write(directory, texture, QByteArray(4, '\0'));
    auto config = readTrail(directory.path(), invalid);
    require(config.has_value() && !invalid, "Valid state must load");

    TrailParts parts;
    parts.move(*config, {0, 0}, 0);
    parts.move(*config, {20, 0}, 10);
    require(parts.parts().size() == 3 && parts.parts().back().pos == QPointF(12, 0),
            "Continuous trail must leave one interval clear behind the cursor");
    parts.stopGrowing();
    parts.expire(509, config->fade());
    require(parts.parts().size() == 3, "Continuous parts must stay alive for 500 ms");
    parts.expire(510, config->fade());
    require(parts.parts().empty(), "Continuous parts must all expire");

    config->disjoint = true;
    parts.move(*config, {0, 0}, 0);
    parts.move(*config, {30, 0}, 50);
    require(parts.parts().size() == 4 && parts.parts().back().pos == QPointF(30, 0),
            "Disjoint trail must fill in stamps between frames");
    parts.expire(150, config->fade());
    require(parts.parts().size() == 3, "Only the oldest disjoint stamp has expired");
    parts.expire(200, config->fade());
    require(parts.parts().empty(), "All disjoint stamps must expire");
    return EXIT_SUCCESS;
}
