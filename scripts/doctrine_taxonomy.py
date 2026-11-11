"""Doctrine taxonomy for synthesized doctrinal pages.

Sixteen loci matching the units.doctrinal_loci tags in Supabase. Each
entry mirrors the topic taxonomy shape (title/deck/phrasings/seo) plus:

  loci — the EXACT doctrinal_loci string in the DB, passed to the
         match RPC as a hard filter so vector ranking happens within
         units actually tagged with this doctrine.
  sof  — a condensed excerpt from Providence's Statement of Faith
         ("We Believe", Sovereign Grace Churches, Editors' Edition
         12.12.2023). Sentences are quoted/condensed from the
         statement text proper (not the editors' footnotes). Fed to
         the synthesis as a citable source [SF] so the page can anchor
         what's preached to what the church confesses.

Audience framing: these are NOT felt-need seeker pages. The reader is
a member, student, or visitor asking "what does this church actually
teach about X?"
"""

DOCTRINES: dict[str, dict] = {
    "theology-proper": {
        "title": "Theology Proper",
        "loci": "Theology Proper",
        "deck": "Who God is — his being, attributes, character, and triune life — as preached at Providence.",
        "seo_title": "What We Teach About God — Theology Proper",
        "meta_desc": "Who God is: his nature, attributes, and triune life. What Providence Community Church in Lenexa KS teaches about God, drawn from the sermons themselves.",
        "phrasings": [
            "the nature and attributes of God",
            "the holiness and glory of God",
            "the Trinity — Father, Son, and Holy Spirit",
            "God's transcendence and immanence",
        ],
        "sof": "There is only one true and living God, who is infinite in being, power, and perfections. God is eternal, independent, and self-sufficient, having life in himself with no need for anyone or anything. He is entirely holy, loving, wise, just, good, merciful, gracious, and truthful. The one true God eternally exists as three persons — Father, Son, and Holy Spirit — each person fully God, sharing the same deity, attributes, and essential nature, yet there is but one God. In his transcendence, God is incomprehensible in his being and actions, yet he reveals himself such that we can know him truly and personally.",
    },
    "christology": {
        "title": "Christology",
        "loci": "Christology",
        "deck": "The person and work of Jesus Christ — incarnation, atonement, resurrection, and reign — as preached at Providence.",
        "seo_title": "What We Teach About Jesus Christ — Christology",
        "meta_desc": "The person and work of Jesus Christ: incarnation, cross, resurrection, and present reign. What Providence Community Church in Lenexa KS teaches, from the sermons.",
        "phrasings": [
            "the person of Jesus Christ — fully God and fully man",
            "the cross and the atonement",
            "the resurrection of Jesus",
            "Christ's present reign and intercession",
        ],
        "sof": "In the fullness of time God the Father sent his eternal Son into the world as Jesus the Christ — fully God and fully man, two whole, perfect, and distinct natures inseparably joined in one person, able to be our all-sufficient savior and the only mediator between God and man. He was crucified under Pontius Pilate, dying a substitutionary death for the sins of his people; on the cross Christ bore our sins, took our punishment, propitiated God's wrath against us, and purchased our redemption. He was buried and arose bodily from the dead on the third day, ascended to heaven, and is now enthroned at the right hand of God, reigning over all things and interceding for his people as their Great High Priest.",
    },
    "pneumatology": {
        "title": "Pneumatology",
        "loci": "Pneumatology",
        "deck": "The person and work of the Holy Spirit — in salvation, sanctification, gifts, and power — as preached at Providence.",
        "seo_title": "What We Teach About the Holy Spirit — Pneumatology",
        "meta_desc": "The person and work of the Holy Spirit: regeneration, indwelling, filling, and gifts. What Providence Community Church in Lenexa KS teaches, from the sermons.",
        "phrasings": [
            "the person of the Holy Spirit",
            "the Spirit's work in regeneration and sanctification",
            "being filled with the Holy Spirit",
            "the gifts of the Spirit",
        ],
        "sof": "The Holy Spirit is the third person of the Trinity, equal in deity, attributes, and nature with the Father and the Son, and with them to be worshipped and glorified. The Spirit glorifies Christ and bears witness to him; he regenerates, indwells all believers, illuminates God's Word, assures them of God's love, intercedes on their behalf, and sanctifies them in conformity to the image of Christ. The Spirit also desires to fill God's people continually with increased power for Christian life and witness, and sovereignly bestows gifts on every believer for the glory of Christ and the building up of the church — gifts we are to earnestly desire and practice until Christ returns.",
    },
    "bibliology": {
        "title": "Bibliology",
        "loci": "Bibliology",
        "deck": "What Scripture is — inspired, inerrant, sufficient, and final — as preached at Providence.",
        "seo_title": "What We Teach About the Bible — Bibliology",
        "meta_desc": "The inspiration, inerrancy, sufficiency, and authority of Scripture. What Providence Community Church in Lenexa KS teaches about the Bible, from the sermons.",
        "phrasings": [
            "the inspiration and authority of Scripture",
            "the sufficiency and clarity of the Bible",
            "how God speaks through his Word",
            "trusting the Bible as God's Word",
        ],
        "sof": "All of Scripture is breathed out by God, delivered through human authors by the inspiration and sovereign agency of the Holy Spirit. We receive the sixty-six books of the Old and New Testaments as the perfect, infallible, and authoritative Word of God; in its original manuscripts the whole of Scripture is inerrant — without error in all it affirms. The Word of God is necessary and wholly sufficient, clear, and is our supreme and final authority and the rule of faith and life: all creeds, confessions, teachings, and prophecies are to be tested by the final authority of God's Word. As we devote ourselves to God's Word, we commune with God himself.",
    },
    "anthropology": {
        "title": "Anthropology",
        "loci": "Anthropology",
        "deck": "What it means to be human — made in God's image, male and female, fallen and redeemable — as preached at Providence.",
        "seo_title": "What We Teach About Humanity — Anthropology",
        "meta_desc": "Made in God's image, male and female, fallen yet redeemable. What Providence Community Church in Lenexa KS teaches about being human, from the sermons.",
        "phrasings": [
            "made in the image of God",
            "what it means to be human",
            "male and female — God's design for gender",
            "human dignity from conception to death",
        ],
        "sof": "God created man, male and female, in his own image as the crown of creation and the object of his special care. All people remain God's image bearers, capable of fellowship with him and possessing intrinsic dignity and value at every stage of life from conception to death. Men and women are both made in the image of God and equal before him in dignity and worth; gender, designated by God through our biological sex, is essential to our identity as male and female, and men and women reflect and represent God in distinct and complementary ways. Redemption in Christ progressively restores fallen men and women to their true humanity as they are conformed to the image of Christ.",
    },
    "hamartiology": {
        "title": "Hamartiology",
        "loci": "Hamartiology",
        "deck": "The nature, depth, and reach of sin — and why it matters that we name it — as preached at Providence.",
        "seo_title": "What We Teach About Sin — Hamartiology",
        "meta_desc": "Original sin, indwelling sin, and the death sin brings. What Providence Community Church in Lenexa KS teaches about sin, drawn from the sermons themselves.",
        "phrasings": [
            "the nature and depth of sin",
            "original sin and the fall",
            "indwelling sin and temptation",
            "the consequences of sin — guilt, corruption, death",
        ],
        "sof": "God originally created man innocent and righteous, but Adam and Eve willfully sinned against their Creator; because God had established Adam as the representative head of the human race, his sin was imputed to all his descendants, bringing guilt, condemnation, and death to humanity. We are all by nature corrupt and inclined to evil from conception. The whole nature of man has been corrupted by the fall, and no part of man is untainted by sin; fallen people are incapable of pleasing God, meriting his favor, or freeing themselves from their bondage to sin. Therefore all people are dead in sin and without hope apart from salvation in Jesus Christ.",
    },
    "soteriology": {
        "title": "Soteriology",
        "loci": "Soteriology",
        "deck": "The gospel and the application of salvation — calling, conversion, justification, adoption — as preached at Providence.",
        "seo_title": "What We Teach About Salvation — Soteriology",
        "meta_desc": "The gospel: effectual calling, regeneration, justification, and adoption. What Providence Community Church in Lenexa KS teaches about salvation, from the sermons.",
        "phrasings": [
            "the gospel of Jesus Christ",
            "justification by faith alone",
            "regeneration, conversion, and the new birth",
            "adoption as God's children",
            "God's grace in election",
        ],
        "sof": "The gospel is the good news of Jesus Christ and all that he did in his life, death, resurrection, and ascension to accomplish salvation for humanity — an objective, historical, divine achievement that remains true and unchanging regardless of human opinion or response. Through the proclamation of the gospel, the Holy Spirit regenerates the elect and brings them into a living union with Christ, enabling them to respond in faith and repentance. Those whom God effectually calls he justifies in Christ, forgiving all of their sins and declaring them righteous; the sole ground of our justification is the righteousness of Christ, imputed to us and received freely by faith. Those whom God justifies, he adopts into his family, granting them the full status, rights, and privileges of beloved sons.",
    },
    "sanctification": {
        "title": "Sanctification",
        "loci": "Sanctification",
        "deck": "Growing in Christ — putting sin to death, persevering, and being conformed to his image — as preached at Providence.",
        "seo_title": "What We Teach About Sanctification — Growing in Christ",
        "meta_desc": "Putting sin to death, growing in grace, persevering to the end. What Providence Community Church in Lenexa KS teaches about sanctification, from the sermons.",
        "phrasings": [
            "sanctification and growing in holiness",
            "putting sin to death — mortification",
            "perseverance of the saints",
            "the means of grace — Word, prayer, fellowship",
            "becoming like Christ",
        ],
        "sof": "All believers, by virtue of their union with Christ, are progressively transformed into his image. Although the ruling power of sin has been broken, remnants of corruption remain in our hearts that we will fight throughout our lives. Resting in Christ's finished work never renders our effort unnecessary but rather enables the joyful pursuit of loving and pleasing God: compelled by grace, believers grow in the knowledge of God, obey Christ's commands, walk by the Spirit, mortify sin, and pursue God's priorities. Believers must persevere in faith and obedience in order to be saved, yet this perseverance is also a gift of God in Christ, who preserves his own and keeps them safe forever. Among the many means of grace, the Word of God, prayer, and fellowship are primary instruments of our sanctification.",
    },
    "ecclesiology": {
        "title": "Ecclesiology",
        "loci": "Ecclesiology",
        "deck": "What the church is, who belongs to it, how it's governed, and what it's for — as preached at Providence.",
        "seo_title": "What We Teach About the Church — Ecclesiology",
        "meta_desc": "The local church: membership, eldership, sacraments, and mission. What Providence Community Church in Lenexa KS teaches about the church, from the sermons.",
        "phrasings": [
            "the local church and church membership",
            "elders, deacons, and church governance",
            "baptism and the Lord's Supper",
            "the mission of the church",
        ],
        "sof": "The local church is the focal point of God's plan to mature his people and save sinners; all Christians are to join themselves as committed members to a specific local church. A true church is marked by the faithful preaching of the Word, the right administration of the sacraments, and the proper exercise of church discipline. Christ has given the offices of elder and deacon to the church: elders occupy the sole office of governance, called to teach, oversee, care for, and protect the flock. The church exists to worship God, to edify and mature his people, and to bear witness to Christ and his kingdom in all the world; its mission is to make disciples of all nations.",
    },
    "covenant-theology": {
        "title": "Covenant Theology",
        "loci": "Covenant Theology",
        "deck": "One unfolding promise from Eden to the new creation — reading the whole Bible as one story — as preached at Providence.",
        "seo_title": "What We Teach About the Covenants — Covenant Theology",
        "meta_desc": "One promise running from Adam through Abraham and David to Christ. How Providence Community Church in Lenexa KS reads the whole Bible as one story.",
        "phrasings": [
            "the covenants of the Bible",
            "the old covenant and the new covenant",
            "Adam and Christ — covenant headship",
            "the promise to Abraham fulfilled in Christ",
        ],
        "sof": "God had established Adam as the representative head of the human race, and as the second Adam, Christ's sinless life of wholehearted obedience obtained the gift of perfect righteousness and eternal life for all of God's elect. Throughout salvation history, God by his Word and Spirit has been calling sinful people out of the whole human race to create a new redeemed humanity. With the giving of the Spirit at Pentecost, God's people were reconstituted as his new covenant church, in continuity with the old covenant people of God but now brought to fulfillment by the work of Christ. Through all the institutions and offices of the Old Testament, the Spirit's work pointed to the ultimate revelation of God through his Son.",
    },
    "providence-sovereignty": {
        "title": "Providence / Sovereignty",
        "loci": "Providence / Sovereignty",
        "deck": "God's active rule over every event — ordaining, governing, and working all things for his glory — as preached at Providence.",
        "seo_title": "What We Teach About God's Sovereignty — Providence",
        "meta_desc": "God ordains all things for his glory and our good. What Providence Community Church in Lenexa KS teaches about God's sovereignty, from the sermons themselves.",
        "phrasings": [
            "the sovereignty of God over all things",
            "God's providence in suffering and circumstance",
            "trusting God's plan when life is hard",
            "divine sovereignty and human responsibility",
        ],
        "sof": "From all eternity, God sovereignly ordained all that exists and all that occurs in his creation, in order to display the fullness of his glory. God's plans are efficacious, always coming to pass, and they are universal, encompassing all the affairs of nature, history, and individual lives. Yet God is not the author of sin, nor do his decrees negate the will of his creatures, who act with the power of willing choice in accord with their nature. As sovereign Lord, he is present with his creation to sustain all things, govern all creatures, and direct all circumstances in accord with his holy and loving will — granting us great comfort and unshakable hope in God's love, wisdom, and faithfulness in this life and in eternity.",
    },
    "eschatology": {
        "title": "Eschatology",
        "loci": "Eschatology",
        "deck": "Death, Christ's return, resurrection, judgment, and the world made new — as preached at Providence.",
        "seo_title": "What We Teach About Last Things — Eschatology",
        "meta_desc": "Christ's return, the resurrection, judgment, and the new creation. What Providence Community Church in Lenexa KS teaches about last things, from the sermons.",
        "phrasings": [
            "the return of Christ",
            "the resurrection of the body",
            "death and what comes after",
            "the new heavens and the new earth",
            "the final judgment",
        ],
        "sof": "At the appointed time known only to God, Jesus Christ will return to the earth in power and glory as Judge and King; Christ's personal, physical, and visible return is the blessed hope of all who trust in him. Death for the Christian has become a doorway to paradise, where our souls enter immediately into God's presence. At the end of the age the just and the unjust will be raised; when the dead in Christ are raised, their perishable bodies will be redeemed and made like Christ's imperishable, glorious body. God's glorified people will inherit the kingdom from which all sin, sorrow, suffering, and death will be banished — and we will enjoy unhindered communion with our triune God forever.",
    },
    "doxology-worship": {
        "title": "Doxology / Worship",
        "loci": "Doxology / Worship",
        "deck": "Why and how we worship — corporate and personal praise, and a life aimed at God's glory — as preached at Providence.",
        "seo_title": "What We Teach About Worship — Doxology",
        "meta_desc": "Corporate worship, singing, prayer, and a life aimed at God's glory. What Providence Community Church in Lenexa KS teaches about worship, from the sermons.",
        "phrasings": [
            "the worship of God",
            "singing and corporate praise",
            "living for the glory of God",
            "gratitude, joy, and delighting in God",
        ],
        "sof": "As the body of Christ, the church exists first to worship God. Governed by Scripture, the church gathers for the teaching of the Word, prayer, the sacraments, congregational singing, fellowship, and mutual edification through the exercise of spiritual gifts. From all eternity, God ordained all that exists and occurs in order to display the fullness of his glory; in everything God supremely acts for his glory and for the good of his people in Christ. The persons of the Trinity — distinct yet of one essence, equal from all eternity — are worthy to be worshipped as the one God: Father, Son, and Holy Spirit.",
    },
    "ethics-moral-theology": {
        "title": "Ethics / Moral Theology",
        "loci": "Ethics / Moral Theology",
        "deck": "How Scripture governs the way Christians actually live — work, money, sex, speech, and the use of the day — as preached at Providence.",
        "seo_title": "What We Teach About Christian Living — Ethics",
        "meta_desc": "Work, money, sexuality, speech, obedience — how Scripture governs real life. What Providence Community Church in Lenexa KS teaches, from the sermons.",
        "phrasings": [
            "Christian ethics and obedience",
            "biblical sexuality, marriage, and singleness",
            "how Christians should live in the world",
            "obeying God's commands with joy",
        ],
        "sof": "God instituted marriage as the union of one man and one woman who complement each other in a one-flesh union that ultimately serves as a type of the union between Christ and his church; this remains the only normative pattern of sexual relations for humanity. Single men and women are no less able to enjoy and honor God and no less important to his purposes. Genuine faith in Jesus always overflows in glad obedience of his commands: compelled by grace, believers grow in the knowledge of God, obey Christ's commands, walk by the Spirit, mortify sin, and pursue God's priorities and purposes. Although such actions are not the ground of our salvation, they demonstrate its authenticity.",
    },
    "pastoral-theology": {
        "title": "Pastoral Theology",
        "loci": "Pastoral Theology",
        "deck": "The work of shepherding — caring for families, counseling the suffering, confronting sin in love — as preached at Providence.",
        "seo_title": "What We Teach About Shepherding — Pastoral Theology",
        "meta_desc": "Shepherding, counseling, discipleship, and care for souls. What Providence Community Church in Lenexa KS teaches about pastoral ministry, from the sermons.",
        "phrasings": [
            "shepherding and pastoral care",
            "counseling the suffering and the doubting",
            "discipleship and spiritual formation",
            "confronting sin in love — church discipline",
        ],
        "sof": "Christ has given the offices of elder and deacon to the church. Elders occupy the sole office of governance and are called to teach, oversee, care for, and protect the flock entrusted to them by the Lord; deacons provide for the various needs of the church through acts of service. God gives these and other people as gifts to serve and equip the saints for the work of ministry, for building up the body of Christ — and men and women alike belong to a royal priesthood in which each member is gifted by God to play a vital role in the life and mission of the church. A true church is marked by the faithful preaching of the Word, the right administration of the sacraments, and the proper exercise of church discipline.",
    },
    "spiritual-warfare": {
        "title": "Spiritual Warfare",
        "loci": "Spiritual Warfare",
        "deck": "The conflict every Christian is in — against indwelling sin, the world's pressures, and unseen opposition — as preached at Providence.",
        "seo_title": "What We Teach About Spiritual Warfare",
        "meta_desc": "The fight against sin, the world, and the devil — and Christ's victory in it. What Providence Community Church in Lenexa KS teaches, from the sermons.",
        "phrasings": [
            "spiritual warfare and the armor of God",
            "fighting temptation and the devil",
            "the world, the flesh, and the devil",
            "Christ's victory over Satan",
        ],
        "sof": "All people are by nature living under the power of Satan — yet raised by the power of God, Christ triumphed over sin, death, and Satan, and as the exalted Lord he empowers his people to be victorious over sin and Satan. Believers continue to live in mortal bodies in a creation subject to futility, opposed by the world, the flesh, and the devil. The Word of God assures us that we are his beloved children, yet such assurance does not remove the reality of suffering, sorrow, and persecution in this present age; fixing our eyes on Jesus, we endure in faith and abound in hope, confident that a day is fast approaching when sin and sorrow will be no more.",
    },
}
